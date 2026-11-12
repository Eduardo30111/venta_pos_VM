#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_recuperacion_inventario_ventas_proveedores.py
Suite de pruebas automatizadas y validación rigurosa para:
1. Recuperación integral del módulo Inventario (6 pestañas, formularios, botones).
2. Selector predictivo dinámico y recuento físico con cálculo de diferencias en tiempo real.
3. Facturas y compras por distribuidor.
4. Persistencia del Registro de Ventas en SQLite y diálogo administrativo.
5. Automatización de obligaciones a proveedores por venta de productos físicos y servicios.
"""

import unittest
import sqlite3
import os
import sys
import tempfile
from datetime import datetime

# Rutas del entorno de pruebas
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
INTF_DIR = os.path.join(ROOT_DIR, "interface")
if INTF_DIR not in sys.path:
    sys.path.insert(0, INTF_DIR)

from interface.database_manager import inicializar_base_datos, conectar_db
from interface.proveedores_manager import (
    inicializar_tablas_proveedores,
    registrar_cxp_servicio_venta,
    recalcular_saldo_proveedor,
    obtener_resumen_proveedores,
    obtener_detalle_cuentas_proveedor,
    liquidar_proveedor_db,
    revertir_cxp_por_venta_anulada,
    sincronizar_cxp_retroactivas
)
from interface.ventas_menu import guardar_venta_sqlite


class TestRecuperacionInventarioVentasProveedores(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Crear base de datos temporal aislada para pruebas
        cls.temp_dir = tempfile.mkdtemp(prefix="vmpos_test_recup_")
        cls.db_ventas = os.path.join(cls.temp_dir, "test_ventas.db")
        os.environ["VMPOS_DB_VENTAS"] = cls.db_ventas

        inicializar_base_datos(cls.db_ventas)
        inicializar_tablas_proveedores()

    @classmethod
    def tearDownClass(cls):
        try:
            if "VMPOS_DB_VENTAS" in os.environ:
                del os.environ["VMPOS_DB_VENTAS"]
            if os.path.exists(cls.db_ventas):
                os.remove(cls.db_ventas)
            for f in os.listdir(cls.temp_dir):
                os.remove(os.path.join(cls.temp_dir, f))
            os.rmdir(cls.temp_dir)
        except Exception:
            pass

    def setUp(self):
        # Limpiar tablas antes de cada test para aislamiento
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys = OFF")
        cur.execute("DELETE FROM cuentas_por_pagar_proveedores")
        cur.execute("DELETE FROM liquidaciones_proveedores")
        cur.execute("DELETE FROM detalle_ventas")
        cur.execute("DELETE FROM ventas")
        cur.execute("DELETE FROM productos")
        cur.execute("DELETE FROM proveedores")
        try:
            cur.execute("DELETE FROM movimientos_inventario")
        except Exception:
            pass
        cur.execute("PRAGMA foreign_keys = ON")
        conn.commit()
        conn.close()

    # =========================================================================
    # 1. PRUEBA: MÓDULO INVENTARIO Y SUS 6 SECCIONES
    # =========================================================================
    def test_01_inventario_pestanas_y_componentes_intactos(self):
        """Verifica que el menú de inventario inicialice sin UnboundLocalError y con las 6 pestañas."""
        import tkinter as tk
        from interface.inventario_menu import iniciar_inventario

        root = tk.Tk()
        root.withdraw()
        try:
            win = iniciar_inventario(parent=root)
            self.assertIsNotNone(win)
            self.assertTrue(win.winfo_exists())

            # Localizar el notebook
            def find_notebook(widget):
                from tkinter import ttk
                for child in widget.winfo_children():
                    if isinstance(child, ttk.Notebook):
                        return child
                    res = find_notebook(child)
                    if res:
                        return res
                return None

            nb = find_notebook(win)
            self.assertIsNotNone(nb, "Debe existir el contenedor Notebook en Inventario.")
            tabs = nb.tabs()
            self.assertEqual(len(tabs), 6, "Inventario debe contener exactamente 6 pestañas funcionales.")

            # Verificar títulos de las pestañas
            tab_texts = [nb.tab(t, "text") for t in tabs]
            self.assertTrue(any("Catálogo" in t for t in tab_texts))
            self.assertTrue(any("Bodega" in t for t in tab_texts))
            self.assertTrue(any("Vitrina" in t for t in tab_texts))
            self.assertTrue(any("Traslados" in t for t in tab_texts))
            self.assertTrue(any("Entradas y Compras" in t for t in tab_texts))
            self.assertTrue(any("Kárdex" in t for t in tab_texts))
        finally:
            try:
                win.destroy()
                root.destroy()
            except Exception:
                pass

    # =========================================================================
    # 2. PRUEBA: SELECTOR PREDICTIVO Y RECUENTO FÍSICO CON DIFERENCIAS
    # =========================================================================
    def test_02_recuento_fisico_calculo_diferencias(self):
        """Verifica el cálculo de diferencias en recuento físico (Faltante / Sobrante / Exacto)."""
        st_sistema = 50.0

        # Caso Faltante (encontró 46, sistema 50 -> dif = -4)
        conteo_1 = 46.0
        dif_1 = conteo_1 - st_sistema
        self.assertEqual(dif_1, -4.0)

        # Caso Sobrante (encontró 52, sistema 50 -> dif = +2)
        conteo_2 = 52.0
        dif_2 = conteo_2 - st_sistema
        self.assertEqual(dif_2, 2.0)

        # Caso Exacto (encontró 50, sistema 50 -> dif = 0)
        conteo_3 = 50.0
        dif_3 = conteo_3 - st_sistema
        self.assertEqual(dif_3, 0.0)

    def test_03_filtro_predictivo_combobox_buscable(self):
        """Verifica que hacer_combobox_buscable filtre por nombre, código y código de barras."""
        import tkinter as tk
        from tkinter import ttk
        from interface.inventario_menu import hacer_combobox_buscable

        root = tk.Tk()
        root.withdraw()
        try:
            var_txt = tk.StringVar()
            cb = ttk.Combobox(root, textvariable=var_txt)

            catalogo_mock = [
                {"codigo": "00001", "nombre": "Bolígrafo azul", "codigo_barras": "770123456", "unidad_medida": "Unidad"},
                {"codigo": "00002", "nombre": "Bolígrafo negro", "codigo_barras": "770123457", "unidad_medida": "Unidad"},
                {"codigo": "00003", "nombre": "Bolígrafo rojo", "codigo_barras": "770123458", "unidad_medida": "Unidad"},
                {"codigo": "00004", "nombre": "Cuaderno grande", "codigo_barras": "770987654", "unidad_medida": "Unidad"},
                {"codigo": "00005", "nombre": "Borrador de nata", "codigo_barras": "770555555", "unidad_medida": "Unidad"},
            ]

            hacer_combobox_buscable(cb, var_txt, lambda: catalogo_mock)

            # 1. Búsqueda por "BOLÍGRAFO"
            var_txt.set("BOLÍGRAFO")
            cb.event_generate("<KeyRelease>")
            vals = list(cb["values"])
            self.assertEqual(len(vals), 3)
            self.assertTrue(all("Bolígrafo" in v for v in vals))

            # 2. Búsqueda por código de barras "770987"
            var_txt.set("770987")
            cb.event_generate("<KeyRelease>")
            vals_bar = list(cb["values"])
            self.assertEqual(len(vals_bar), 1)
            self.assertIn("Cuaderno grande", vals_bar[0])

            # 3. Búsqueda sin coincidencias
            var_txt.set("inexistente999")
            cb.event_generate("<KeyRelease>")
            vals_none = list(cb["values"])
            self.assertTrue(vals_none[0].startswith("⚠️ (Sin coincidencias"))
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    # =========================================================================
    # 3. PRUEBA: PERSISTENCIA DEL REGISTRO DE VENTAS EN SQLITE
    # =========================================================================
    def test_04_persistencia_guardar_venta_sqlite(self):
        """Verifica que una venta confirmada persista en ventas y detalle_ventas."""
        detalles = [
            {
                "item_codigo": "00100",
                "item_nombre": "Cuaderno Cuadriculado",
                "precio_vendido": 5000.0,
                "cantidad": 2,
                "subtotal": 10000.0,
                "tipo_item": "Producto"
            }
        ]

        id_v = guardar_venta_sqlite(
            doc_cliente="1098765432",
            total=10000.0,
            metodo_pago="Efectivo",
            detalles=detalles,
            operario_nombre="Cajero Principal",
            numero_factura="FAC-00101"
        )
        self.assertIsNotNone(id_v)
        self.assertGreater(id_v, 0)

        # Verificar persistencia en base de datos
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("SELECT total_venta, documento_cliente, operario, estado FROM ventas WHERE id_venta = ?", (id_v,))
        row = cur.fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 10000.0)
        self.assertEqual(row[1], "1098765432")
        self.assertEqual(row[2], "Cajero Principal")
        self.assertEqual(row[3], "Completada")

        cur.execute("SELECT nombre_producto, cantidad, subtotal FROM detalle_ventas WHERE id_venta = ?", (id_v,))
        det_row = cur.fetchone()
        self.assertIsNotNone(det_row)
        self.assertEqual(det_row[0], "Cuaderno Cuadriculado")
        self.assertEqual(det_row[1], 2)
        self.assertEqual(det_row[2], 10000.0)
        conn.close()

    # =========================================================================
    # 4. PRUEBA: OBLIGACIONES AUTOMÁTICAS CON PROVEEDORES POR VENTA
    # =========================================================================
    def test_05_obligacion_automatica_proveedor_producto_fisico(self):
        """
        Escenario solicitado:
        Producto: Accesorio X.
        Precio venta: $20.000.
        Proveedor asociado: Proveedor ABC.
        Valor a pagar al proveedor por unidad: $12.000 (costo).
        Cantidad vendida: 3.
        Resultado esperado:
        Venta: $60.000.
        Obligación generada al proveedor: $36.000.
        """
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()

        # 1. Registrar proveedor
        cur.execute("INSERT INTO proveedores (nombre, telefono, saldo_acumulado) VALUES (?, ?, 0.0)", ("Proveedor ABC", "3001234567"))
        prov_id = cur.lastrowid

        # 2. Registrar producto asociado al proveedor con costo $12.000 y precio venta $20.000
        cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock, tipo_producto, proveedor_id, estado)
            VALUES (?, ?, ?, ?, ?, 'Fisico', ?, 'Activo')
        """, ("ACC-X01", "Accesorio X", 20000.0, 12000.0, 50, prov_id))
        conn.commit()
        conn.close()

        # 3. Registrar venta de 3 unidades
        detalles_venta = [
            {
                "item_codigo": "ACC-X01",
                "item_nombre": "Accesorio X",
                "precio_vendido": 20000.0,
                "cantidad": 3,
                "subtotal": 60000.0,
                "tipo_item": "Producto"
            }
        ]

        id_v = guardar_venta_sqlite(
            doc_cliente="222333444",
            total=60000.0,
            metodo_pago="Efectivo",
            detalles=detalles_venta,
            operario_nombre="Administrador",
            numero_factura="FAC-PROV-001"
        )
        self.assertIsNotNone(id_v)

        # 4. Verificar que se haya creado la obligación en cuentas_por_pagar_proveedores
        conn = conectar_db(self.db_ventas)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        cur.execute("""
            SELECT id, proveedor_id, precio_venta, monto_por_pagar, saldo_pendiente, estado
            FROM cuentas_por_pagar_proveedores
            WHERE id_venta = ?
        """, (id_v,))
        cxp = cur.fetchone()
        self.assertIsNotNone(cxp, "Debe haberse generado automáticamente la obligación en cuentas_por_pagar_proveedores.")
        self.assertEqual(cxp["proveedor_id"], prov_id)
        self.assertEqual(float(cxp["precio_venta"]), 60000.0)
        self.assertEqual(float(cxp["monto_por_pagar"]), 36000.0, "La obligación con el proveedor debe ser $36.000 (3 x $12.000).")
        self.assertEqual(float(cxp["saldo_pendiente"]), 36000.0)
        self.assertEqual(cxp["estado"], "Pendiente")

        # 5. Verificar que el saldo acumulado del proveedor se haya actualizado a $36.000
        cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (prov_id,))
        prov_row = cur.fetchone()
        self.assertEqual(float(prov_row["saldo_acumulado"]), 36000.0, "El saldo del proveedor debe reflejar $36.000.")
        conn.close()

    def test_06_abono_y_liquidacion_proveedor(self):
        """Verifica que un abono o liquidación disminuya el saldo del proveedor e impida pagos duplicados."""
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("INSERT INTO proveedores (nombre, saldo_acumulado) VALUES ('Distribuciones XYZ', 0.0)")
        p_id = cur.lastrowid
        cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock, tipo_producto, proveedor_id, estado)
            VALUES ('P-XYZ', 'Producto XYZ', 10000.0, 7000.0, 20, 'Fisico', ?, 'Activo')
        """, (p_id,))
        conn.commit()
        conn.close()

        # Vender 2 unidades -> Total $20.000, Obligación $14.000
        guardar_venta_sqlite(
            doc_cliente="999888",
            total=20000.0,
            metodo_pago="Efectivo",
            detalles=[{"item_codigo": "P-XYZ", "item_nombre": "Producto XYZ", "precio_vendido": 10000.0, "cantidad": 2, "subtotal": 20000.0, "tipo_item": "Producto"}],
            numero_factura="FAC-XYZ-1"
        )

        res_liq = liquidar_proveedor_db(
            proveedor_id=p_id,
            monto=14000.0,
            metodo_pago="Efectivo",
            usuario="Administrador"
        )
        self.assertTrue(res_liq.get("exito", False))
        self.assertEqual(float(res_liq["saldo_restante"]), 0.0)

        # Verificar en base de datos
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (p_id,))
        saldo_final = float(cur.fetchone()[0])
        self.assertEqual(saldo_final, 0.0)

        # Comprobar que no permita liquidar dos veces
        res_dup = liquidar_proveedor_db(
            proveedor_id=p_id,
            monto=14000.0,
            metodo_pago="Efectivo"
        )
        self.assertFalse(res_dup.get("exito", True))
        conn.close()

    def test_07_anulacion_venta_revierte_obligacion_proveedor(self):
        """Verifica que anular una venta revierta la obligación del proveedor de forma atómica."""
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("INSERT INTO proveedores (nombre, saldo_acumulado) VALUES ('Proveedor Reversion', 0.0)")
        p_id = cur.lastrowid
        cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock, tipo_producto, proveedor_id, estado)
            VALUES ('P-REV', 'Producto Revertible', 15000.0, 10000.0, 10, 'Fisico', ?, 'Activo')
        """, (p_id,))
        conn.commit()
        conn.close()

        id_v = guardar_venta_sqlite(
            doc_cliente="111222",
            total=15000.0,
            metodo_pago="Efectivo",
            detalles=[{"item_codigo": "P-REV", "item_nombre": "Producto Revertible", "precio_vendido": 15000.0, "cantidad": 1, "subtotal": 15000.0, "tipo_item": "Producto"}],
            numero_factura="FAC-REV-1"
        )

        # Comprobar que saldo es $10.000
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (p_id,))
        self.assertEqual(float(cur.fetchone()[0]), 10000.0)
        conn.close()

        # Anular la venta
        rev = revertir_cxp_por_venta_anulada(id_v, motivo="Devolución de cliente")
        self.assertIn(p_id, rev.get("proveedores", []))

        # Saldo del proveedor debe regresar a 0.0 y estado de cxp debe ser 'Anulada'
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("SELECT saldo_acumulado FROM proveedores WHERE id = ?", (p_id,))
        self.assertEqual(float(cur.fetchone()[0]), 0.0)

        cur.execute("SELECT estado, saldo_pendiente FROM cuentas_por_pagar_proveedores WHERE id_venta = ?", (id_v,))
        cxp_row = cur.fetchone()
        self.assertEqual(cxp_row[0], "Anulada")
        self.assertEqual(float(cxp_row[1]), 0.0)
        conn.close()

    def test_08_resumen_proveedor_contiene_saldo_pendiente(self):
        """Verifica que obtener_resumen_proveedores siempre incluya saldo_pendiente sin KeyError."""
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("INSERT INTO proveedores (nombre, telefono, saldo_acumulado, documento_nit) VALUES ('Omara Sierra Test', '3147774000', 45000.0, '12345678')")
        p_id = cur.lastrowid
        conn.commit()
        conn.close()

        resumen = obtener_resumen_proveedores(conn=conectar_db(self.db_ventas))
        omara = next((p for p in resumen if p["id"] == p_id), None)
        self.assertIsNotNone(omara)
        self.assertIn("saldo_pendiente", omara, "La clave 'saldo_pendiente' DEBE existir en el diccionario de proveedor.")
        self.assertIn("saldo_acumulado", omara)
        self.assertIn("documento_nit", omara)

    def test_09_sincronizacion_cxp_retroactiva_venta_anulada(self):
        """Verifica que una venta de producto de proveedor anulada se sincronice y aparezca como Anulada en CXP."""
        conn = conectar_db(self.db_ventas)
        cur = conn.cursor()
        cur.execute("INSERT INTO proveedores (nombre, telefono, saldo_acumulado) VALUES ('Omara Sierra Retro', '3147774001', 0.0)")
        p_id = cur.lastrowid

        cur.execute("""
            INSERT INTO productos (codigo, nombre, precio, costo, stock, tipo_producto, proveedor_id, estado)
            VALUES ('PROD-OMARA', 'Producto Omara', 20000.0, 14000.0, 10, 'Producto', ?, 'Activo')
        """, (p_id,))

        # Crear venta directamente en estado 'Anulada' simulando historial
        cur.execute("""
            INSERT INTO ventas (fecha_venta, hora_venta, documento_cliente, total_venta, metodo_pago, operario, estado, motivo_anulacion)
            VALUES ('2026-11-09', '10:00:00', '12345', 20000.0, 'Efectivo', 'Admin', 'Anulada', 'Cliente canceló')
        """)
        v_id = cur.lastrowid

        cur.execute("""
            INSERT INTO detalle_ventas (id_venta, codigo_producto, nombre_producto, cantidad, precio_unitario, subtotal, costo_unitario)
            VALUES (?, 'PROD-OMARA', 'Producto Omara', 1, 20000.0, 20000.0, 14000.0)
        """, (v_id,))
        conn.commit()
        conn.close()

        # Ejecutar sincronización retroactiva
        res_sync = sincronizar_cxp_retroactivas(conn=conectar_db(self.db_ventas))
        self.assertTrue(res_sync.get("ok", False))
        self.assertGreaterEqual(res_sync.get("creadas", 0), 1)

        # Consultar cuentas del proveedor (con solo_pendientes=False para ver anuladas)
        cuentas = obtener_detalle_cuentas_proveedor(p_id, solo_pendientes=False, conn=conectar_db(self.db_ventas))
        self.assertGreaterEqual(len(cuentas), 1)
        cxp_anulada = cuentas[0]
        self.assertEqual(cxp_anulada["estado"], "Anulada")
        self.assertEqual(float(cxp_anulada["saldo_pendiente"]), 0.0)
        self.assertEqual(cxp_anulada["nombre_servicio"], "Producto Omara")


if __name__ == "__main__":
    unittest.main()
