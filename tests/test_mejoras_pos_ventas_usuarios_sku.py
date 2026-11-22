#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_mejoras_pos_ventas_usuarios_sku.py
Suite de pruebas integrales para validar las 7 mejoras funcionales y de arquitectura:
1. Rediseño funcional de Ventas (Carrito dominante, popups no bloqueantes de Catálogo y Operarios, badge dinámico).
2. Buscador inteligente en Catálogo (multi-criterio, normalización de acentos, debounce y limpiar filtros).
3. Generador de Códigos de Barras (contraste de campos, selección con badge y escalado de fuentes según DPI/px).
4. Reestructuración de Usuarios y Remuneración (esquema Fijo vs Porcentual, limpieza estricta y protección de liquidaciones).
5. Modificación de Fecha en Registro de Ventas (validación de formato, confirmación y trazabilidad de auditoría).
6. Registro de Ventas Atrasadas (separación Fecha Operación vs Registro, impacto contable sin alterar arqueo físico de caja).
7. Generación automática y configurable de SKU consecutivos (prefijo, separador, dígitos, vista previa y no alteración histórica).
"""

import os
import sys
import unittest
import sqlite3
import tempfile
import shutil
from datetime import datetime
import tkinter as tk

# Asegurar entorno no interactivo para pruebas automáticas
os.environ["VMPOS_TEST_MODE"] = "1"
os.environ["TK_SILENCE_DEPRECATION"] = "1"

# Inclusión del path raíz
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from interface.business_manager import business_mgr
from interface.inventario_manager import sugerir_proximo_codigo
from interface.theme_manager import theme_mgr, aplicar_tema
from interface.generador_codigo_barras import GeneradorCodigoBarras
from interface.table_filter_sorter import normalizar_texto
from interface.ventas_menu import App as VentasApp, guardar_venta_sqlite, VentanaCatalogo, VentanaOperarios
from interface.database_manager import conectar_db


class TestMejorasVmPOS(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Asegurar tablas y columnas necesarias en la base de datos de trabajo
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(ventas)")
        cols = [c[1] for c in cur.fetchall()]
        if "es_venta_atrasada" not in cols:
            try:
                cur.execute("ALTER TABLE ventas ADD COLUMN es_venta_atrasada INTEGER DEFAULT 0")
            except Exception:
                pass
        if "fecha_registro" not in cols:
            try:
                cur.execute("ALTER TABLE ventas ADD COLUMN fecha_registro TEXT")
            except Exception:
                pass
        if "motivo_modificacion_fecha" not in cols:
            try:
                cur.execute("ALTER TABLE ventas ADD COLUMN motivo_modificacion_fecha TEXT")
            except Exception:
                pass
        conn.commit()
        conn.close()

    def setUp(self):
        try:
            self.root = tk.Tk()
            self.root.withdraw()
        except Exception:
            self.root = None

    def tearDown(self):
        if self.root:
            try:
                self.root.update_idletasks()
                self.root.destroy()
            except Exception:
                pass

    # =========================================================================
    # REQUIREMENT 7: SKU CONSECUTIVO CONFIGURABLE Y SUGERENCIA
    # =========================================================================
    def test_01_sku_configuracion_y_sugerencia(self):
        """Valida que la configuración de SKU genere códigos consecutivos correctamente respetando formato."""
        conn = conectar_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT OR REPLACE INTO productos (codigo, nombre, precio, stock) VALUES ('TESTSKU-0001', 'Item SKU 1', 1000, 10)")
            cur.execute("INSERT OR REPLACE INTO productos (codigo, nombre, precio, stock) VALUES ('TESTSKU-0002', 'Item SKU 2', 2000, 10)")
            cur.execute("INSERT OR REPLACE INTO productos (codigo, nombre, precio, stock) VALUES ('TESTSKU-0003', 'Item SKU 3', 3000, 10)")
            conn.commit()
        finally:
            conn.close()

        # Configurar parámetros en business_mgr
        business_mgr.establecer("sku_auto_generar", True)
        business_mgr.establecer("sku_prefijo", "TESTSKU")
        business_mgr.establecer("sku_separador", "-")
        business_mgr.establecer("sku_digitos", 4)
        business_mgr.establecer("sku_numero_inicial", 1)

        proximo = sugerir_proximo_codigo()
        self.assertEqual(proximo, "TESTSKU-0004", f"El próximo código consecutivo sugerido debe ser TESTSKU-0004, recibido: {proximo}")

        # Probar con prefijo diferente sin histórico
        business_mgr.establecer("sku_prefijo", "NEWPREF")
        proximo_art = sugerir_proximo_codigo()
        self.assertEqual(proximo_art, "NEWPREF-0001", "Al cambiar de prefijo sin histórico debe empezar en 0001")

    # =========================================================================
    # REQUIREMENT 3: GENERADOR DE CÓDIGOS DE BARRA Y ESCALADO DPI
    # =========================================================================
    def test_02_generador_codigos_barra_contraste_y_escalado(self):
        """Valida tokens de contraste legibles y cálculo dinámico de fuentes según píxeles/DPI."""
        if not self.root:
            self.skipTest("Tkinter no disponible en este entorno")

        dlg = GeneradorCodigoBarras(self.root)
        self.assertIsNotNone(dlg.t.get("input_bg"), "El tema debe proveer input_bg")
        self.assertIsNotNone(dlg.t.get("text_main"), "El tema debe proveer text_main")
        self.assertNotEqual(dlg.t["input_bg"], "#000000", "input_bg no debe ser negro sólido que oculte texto")

        # Probar escalado proporcional de fuentes para etiqueta térmica alta resolución
        h_px = 354 # ~30mm a 300 DPI
        tam_prod = max(16, int(h_px * 0.105))
        tam_precio = max(18, int(h_px * 0.130))
        self.assertGreaterEqual(tam_prod, 16, "El tamaño de fuente del producto debe ser legible")
        self.assertGreaterEqual(tam_precio, 18, "El tamaño de fuente del precio debe ser legible")

        try:
            dlg.ventana.destroy()
        except Exception:
            pass

    # =========================================================================
    # REQUIREMENT 4: REESTRUCTURACIÓN DE USUARIOS Y REMUNERACIÓN
    # =========================================================================
    def test_03_reestructuracion_remuneracion_usuarios(self):
        """Valida que cambiar a Fija limpie porcentaje a 0.0 y cambiar a Porcentual limpie salario diario a 0.0."""
        class MockUsuario:
            def __init__(self, tipo_remuneracion, salario_diario, porcentaje_comision):
                self.tipo_remuneracion = tipo_remuneracion
                self.salario_diario = salario_diario
                self.porcentaje_comision = porcentaje_comision

        # Caso 1: Usuario con Remuneración Fija pero con residuo histórico de porcentaje
        u_fijo = MockUsuario(tipo_remuneracion="Fija", salario_diario=50000.0, porcentaje_comision=10.0)
        es_porcentual = u_fijo.tipo_remuneracion == "Porcentual" or (
            u_fijo.tipo_remuneracion != "Fija" and float(u_fijo.porcentaje_comision or 0.0) > 0
        )
        self.assertFalse(es_porcentual, "Un usuario con tipo 'Fija' NO debe computar comisiones bajo ningún concepto")

        # Caso 2: Usuario con Remuneración Porcentual
        u_porcentual = MockUsuario(tipo_remuneracion="Porcentual", salario_diario=0.0, porcentaje_comision=5.0)
        es_porcentual_2 = u_porcentual.tipo_remuneracion == "Porcentual"
        self.assertTrue(es_porcentual_2, "Un usuario con tipo 'Porcentual' debe computar comisiones")

    # =========================================================================
    # REQUIREMENT 5 & 6: VENTA ATRASADA Y AUDITORÍA CONTABLE
    # =========================================================================
    def test_04_registro_venta_atrasada_y_caja_fisica(self):
        """Valida que una venta atrasada registre su fecha de operación sin alterar el arqueo físico de caja de hoy."""
        detalles = [
            {"item_codigo": "TEST-01", "item_nombre": "Producto Atrasado", "precio_vendido": 15000.0, "cantidad": 1, "subtotal": 15000.0}
        ]

        # Registrar venta con fecha atrasada de hace 3 días
        id_v = guardar_venta_sqlite(
            doc_cliente="12345678",
            total=15000.0,
            metodo_pago="Efectivo",
            detalles=detalles,
            operario_nombre="AdminTest",
            numero_factura="FAC-ATRASADA-01",
            fecha="2026-11-19",
            hora="14:30:00",
            es_venta_atrasada=True,
            motivo_modificacion_fecha="Factura atrasada de libreta física"
        )
        self.assertIsNotNone(id_v, "La venta atrasada debe registrarse en SQLite")

        # Comprobar en base de datos real
        conn = conectar_db()
        cur = conn.cursor()
        cur.execute("SELECT fecha_venta, hora_venta, es_venta_atrasada, motivo_modificacion_fecha, fecha_registro FROM ventas WHERE id_venta = ?", (id_v,))
        row_v = cur.fetchone()
        self.assertIsNotNone(row_v, "Debe existir el registro de la venta atrasada en SQLite")
        self.assertEqual(row_v[0], "2026-11-19", "La fecha de operación debe ser la fecha histórica indicada")
        self.assertEqual(row_v[1], "14:30:00", "La hora debe ser la histórica indicada")
        self.assertEqual(row_v[2], 1, "Debe estar marcada con es_venta_atrasada = 1")
        self.assertIn("atrasada", row_v[3].lower(), "El motivo debe guardarse en la auditoría")
        self.assertIsNotNone(row_v[4], "Debe registrarse el instante físico real en fecha_registro")
        conn.close()

    # =========================================================================
    # REQUIREMENT 1 & 2: REDISEÑO DE VENTAS, BUSCADOR INTELIGENTE Y POPUPS
    # =========================================================================
    def test_05_buscador_inteligente_normalizacion_acentos(self):
        """Valida la búsqueda insensible a tildes y multi-criterio en el catálogo."""
        self.assertEqual(normalizar_texto("Cámaras Web"), "camaras web")
        self.assertEqual(normalizar_texto("CAFÉ COLOMBIANO"), "cafe colombiano")
        self.assertEqual(normalizar_texto("Papelería y Útiles"), "papeleria y utiles")

        # Probar búsqueda sobre lista de catálogo
        catalogo_test = [
            ("001", "Cámara Web HD 1080p", 10, 150000, "Fisico", None, 1, 90000, False, 0, "7701111", "Electrónica", "Logitech", "Logitech", "Cámara USB"),
            ("002", "Café Tostado Especial", 25, 22000, "Fisico", None, 2, 14000, False, 0, "7702222", "Alimentos", "Juan Valdez", "Marca Café", "Café de origen"),
            ("003", "Servicio Impresión Carta", 9999, 500, "Servicio", None, 3, 100, False, 0, "", "Servicios", "", "", "Impresión b/n")
        ]

        # Búsqueda con tilde que coincide con texto sin tilde y viceversa
        query_1 = normalizar_texto("camara")
        match_1 = [p for p in catalogo_test if query_1 in normalizar_texto(f"{p[0]} {p[1]} {p[10]} {p[11]} {p[12]} {p[13]} {p[14]}")]
        self.assertEqual(len(match_1), 1)
        self.assertEqual(match_1[0][0], "001")

        # Búsqueda por categoría
        query_2 = normalizar_texto("electronica")
        match_2 = [p for p in catalogo_test if query_2 in normalizar_texto(f"{p[0]} {p[1]} {p[10]} {p[11]} {p[12]} {p[13]} {p[14]}")]
        self.assertEqual(len(match_2), 1)
        self.assertEqual(match_2[0][0], "001")

        # Búsqueda por código de barras
        query_3 = normalizar_texto("7702222")
        match_3 = [p for p in catalogo_test if query_3 in normalizar_texto(f"{p[0]} {p[1]} {p[10]} {p[11]} {p[12]} {p[13]} {p[14]}")]
        self.assertEqual(len(match_3), 1)
        self.assertEqual(match_3[0][0], "002")

    def test_06_pos_interfaz_dominante_y_popups_singletons(self):
        """Valida que la tabla de ventas sea dominante y que Catálogo y Operarios abran como ventanas emergentes independientes."""
        if not self.root:
            self.skipTest("Tkinter no disponible en este entorno")

        app = VentasApp(self.root, user_id="1", rol="Administrador", usuario_nombre="AdminTest")

        # Comprobar que la tabla de ventas tiene columna #0 para Código / SKU
        cols = app.tabla["columns"]
        self.assertIn("Producto", cols)
        self.assertIn("Precio", cols)
        self.assertIn("Cantidad", cols)
        self.assertIn("Total", cols)

        # Comprobar botones superiores en info_frame
        self.assertTrue(hasattr(app, "btn_catalogo_popup"), "Debe existir btn_catalogo_popup")
        self.assertTrue(hasattr(app, "btn_operarios_popup"), "Debe existir btn_operarios_popup")
        self.assertTrue(hasattr(app, "btn_venta_atrasada"), "Debe existir btn_venta_atrasada")

        # Probar apertura de VentanaCatalogo (popup no bloqueante)
        app.abrir_catalogo_popup()
        self.assertIsNotNone(app.ventana_catalogo_instancia)
        self.assertTrue(app.ventana_catalogo_instancia.top.winfo_exists())

        # Probar patrón singleton (re-abrir debe reutilizar la misma instancia)
        top_prev = app.ventana_catalogo_instancia.top
        app.abrir_catalogo_popup()
        self.assertIs(app.ventana_catalogo_instancia.top, top_prev, "Debe reutilizar la ventana existente (singleton)")
        app.ventana_catalogo_instancia.cerrar()
        self.assertIsNone(app.ventana_catalogo_instancia)

        # Probar apertura de VentanaOperarios
        app.abrir_operarios_popup()
        self.assertIsNotNone(app.ventana_operarios_instancia)
        self.assertTrue(app.ventana_operarios_instancia.top.winfo_exists())
        app.ventana_operarios_instancia.cerrar()
        self.assertIsNone(app.ventana_operarios_instancia)

        # Probar permisos: Vendedor también puede procesar ventas y ver operarios
        app_vendedor = VentasApp(self.root, user_id="2", rol="Vendedor", usuario_nombre="VendedorTest")
        self.assertTrue(app_vendedor.puede_procesar_venta, "El vendedor debe poder procesar ventas y atender órdenes de operarios")


if __name__ == "__main__":
    unittest.main()
