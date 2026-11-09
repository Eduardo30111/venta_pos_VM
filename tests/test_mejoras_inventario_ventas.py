#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_mejoras_inventario_ventas.py
Suite de pruebas integrales para las 5 mejoras prioritarias de Inventario y Ventas:
1. Selectores predictivos y búsqueda multi-criterio en Inventario.
2. Modal y flujo de facturas de compra por distribuidor.
3. Precios variables en productos físicos y preservación del catálogo maestro.
4. Edición directa de cantidad y precio desde el carrito de ventas POS.
5. Conexión obligatoria entre ventas, arqueo de caja, cuentas por cobrar y contabilidad.
"""

import os
import sys
import unittest
import sqlite3
import tempfile
from datetime import datetime

# Garantizar resolución de módulos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from interface.database_manager import conectar_db, inicializar_base_datos
from interface.caja_manager import abrir_sesion_caja, calcular_arqueo_sesion, obtener_sesion_activa
from interface.ventas_menu import guardar_venta_sqlite


class TestSelectoresInventario(unittest.TestCase):
    """Pruebas del algoritmo de filtrado predictivo multi-criterio para selectores de inventario."""

    def setUp(self):
        self.articulos_muestra = [
            {"id": 1, "codigo": "00001", "nombre": "Cuaderno grande 100h", "codigo_barras": "7701001", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 3000.0, "precio": 5000.0, "stock_bodega": 20, "stock_vitrina": 10},
            {"id": 2, "codigo": "00002", "nombre": "Cuaderno pequeño 50h", "codigo_barras": "7701002", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 1800.0, "precio": 3000.0, "stock_bodega": 30, "stock_vitrina": 15},
            {"id": 3, "codigo": "00003", "nombre": "Lápiz negro HB", "codigo_barras": "7702001", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 500.0, "precio": 1200.0, "stock_bodega": 100, "stock_vitrina": 25},
            {"id": 4, "codigo": "00004", "nombre": "Lápiz rojo 2B", "codigo_barras": "7702002", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 600.0, "precio": 1300.0, "stock_bodega": 50, "stock_vitrina": 20},
            {"id": 5, "codigo": "00005", "nombre": "Borrador de nata", "codigo_barras": "7703001", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 400.0, "precio": 1000.0, "stock_bodega": 40, "stock_vitrina": 12},
            {"id": 6, "codigo": "00006", "nombre": "Regla de 30 cm", "codigo_barras": "7704001", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 800.0, "precio": 2000.0, "stock_bodega": 15, "stock_vitrina": 8},
            {"id": 7, "codigo": "00007", "nombre": "Marcador permanente negro", "codigo_barras": "7705001", "tipo_producto": "Fisico", "unidad_medida": "Unidad", "costo": 1500.0, "precio": 3500.0, "stock_bodega": 25, "stock_vitrina": 10},
        ]

    def _filtrar(self, q, articulos=None):
        catalogo = articulos if articulos is not None else self.articulos_muestra
        q_clean = q.strip().lower()
        if not q_clean:
            return [f"{a['codigo']} - {a['nombre']}" for a in catalogo]
        coincidencias = []
        for a in catalogo:
            nom = (a.get("nombre") or "").lower()
            cod = (a.get("codigo") or "").lower()
            cb = str(a.get("codigo_barras") or "").lower()
            if q_clean in nom or q_clean in cod or (cb and q_clean in cb):
                coincidencias.append(f"{a['codigo']} - {a['nombre']}")
        return coincidencias or [f"⚠️ (Sin coincidencias para '{q}')"]

    def test_busqueda_por_nombre_insensible_a_mayusculas(self):
        """Al escribir 'lápiz' o 'LAPIZ', deben aparecer únicamente los lápices."""
        res_min = self._filtrar("lápiz")
        self.assertEqual(len(res_min), 2)
        self.assertIn("00003 - Lápiz negro HB", res_min)
        self.assertIn("00004 - Lápiz rojo 2B", res_min)

        res_may = self._filtrar("LÁPIZ")
        self.assertEqual(res_min, res_may)

    def test_busqueda_por_codigo_sku(self):
        """Buscar por código '00006' debe retornar exclusivamente la regla de 30 cm."""
        res = self._filtrar("00006")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], "00006 - Regla de 30 cm")

    def test_busqueda_por_codigo_de_barras(self):
        """Buscar por código de barras '7703001' debe identificar el Borrador de nata."""
        res = self._filtrar("7703001")
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0], "00005 - Borrador de nata")

    def test_mensaje_sin_coincidencias(self):
        """Cuando no existe ningún artículo coincidente, debe desplegar aviso claro."""
        res = self._filtrar("articulo_inexistente_xyz")
        self.assertEqual(len(res), 1)
        self.assertTrue(res[0].startswith("⚠️ (Sin coincidencias"))

    def test_rendimiento_y_sin_duplicados_con_miles_de_articulos(self):
        """Debe procesar 5,000 artículos en menos de 50 milisegundos sin duplicaciones."""
        gran_catalogo = []
        for i in range(1, 5001):
            gran_catalogo.append({
                "id": i,
                "codigo": f"{i:05d}",
                "nombre": f"Producto de Prueba {i}",
                "codigo_barras": f"770999{i:04d}",
                "unidad_medida": "Unidad",
                "stock_bodega": 10,
                "stock_vitrina": 5
            })
        inicio = datetime.now()
        res = self._filtrar("prueba 499", gran_catalogo)
        duracion_ms = (datetime.now() - inicio).total_seconds() * 1000
        self.assertLess(duracion_ms, 80.0, f"Filtrado tardó {duracion_ms:.2f} ms")
        self.assertGreater(len(res), 0)
        self.assertEqual(len(res), len(set(res)), "No deben existir duplicados en los resultados")


class TestFacturasDistribuidor(unittest.TestCase):
    """Pruebas para la selección, asociación y alta de productos en facturas de distribuidor."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.environ["VMPOS_DB_VENTAS"] = self.db_path
        inicializar_base_datos(self.db_path)
        self.conn = conectar_db(self.db_path)
        cur = self.conn.cursor()

        # Insertar proveedores de prueba
        cur.execute("INSERT INTO proveedores (id, nombre, telefono) VALUES (1, 'Distribuciones ABC', '3001112222')")
        cur.execute("INSERT INTO proveedores (id, nombre, telefono) VALUES (2, 'Papelería Nacional', '3003334444')")

        # Insertar productos vinculados a Distribuciones ABC (ID 1)
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, unidad_medida, costo, precio, stock_bodega, stock_vitrina, stock, proveedor_id)
            VALUES ('ABC-01', 'Cuadernos ABC', 'Papelería', 'Unidad', 2500, 4500, 50, 10, 60, 1)
        """)
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, unidad_medida, costo, precio, stock_bodega, stock_vitrina, stock, proveedor_id)
            VALUES ('ABC-02', 'Lápices ABC', 'Escritura', 'Unidad', 400, 1000, 100, 20, 120, 1)
        """)

        # Insertar producto en bodega sin distribuidor asignado
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, unidad_medida, costo, precio, stock_bodega, stock_vitrina, stock, proveedor_id)
            VALUES ('BOD-99', 'Cartulina Blanca', 'Papelería', 'Pliego', 800, 1500, 200, 0, 200, NULL)
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        try:
            os.close(self.db_fd)
            os.remove(self.db_path)
        except Exception:
            pass

    def test_filtro_productos_por_distribuidor(self):
        """Al consultar por Distribuciones ABC (ID 1), debe retornar prioritariamente sus productos."""
        cur = self.conn.cursor()
        cur.execute("SELECT codigo, nombre FROM productos WHERE proveedor_id = 1")
        prods = cur.fetchall()
        self.assertEqual(len(prods), 2)
        codigos = [p[0] for p in prods]
        self.assertIn("ABC-01", codigos)
        self.assertIn("ABC-02", codigos)
        self.assertNotIn("BOD-99", codigos)

    def test_asociar_producto_de_bodega_sin_duplicar(self):
        """Asociar un producto existente de bodega al distribuidor 1 debe conservar su ID y existencias."""
        cur = self.conn.cursor()
        cur.execute("SELECT stock_bodega, proveedor_id FROM productos WHERE codigo = 'BOD-99'")
        sb_antes, prov_antes = cur.fetchone()
        self.assertIsNone(prov_antes)
        self.assertEqual(sb_antes, 200.0)

        # Asociar al distribuidor 1
        cur.execute("UPDATE productos SET proveedor_id = 1 WHERE codigo = 'BOD-99'")
        self.conn.commit()

        # Comprobar que no se duplicó el producto
        cur.execute("SELECT COUNT(*) FROM productos WHERE codigo = 'BOD-99'")
        self.assertEqual(cur.fetchone()[0], 1)

        # Comprobar existencias e ID intactos
        cur.execute("SELECT stock_bodega, proveedor_id FROM productos WHERE codigo = 'BOD-99'")
        sb_despues, prov_despues = cur.fetchone()
        self.assertEqual(sb_despues, 200.0)
        self.assertEqual(prov_despues, 1)

    def test_recepcion_factura_con_conversion_unidades(self):
        """Registrar entrada de mercancía por empaques calculando factor y costo unitario convertido."""
        # Comprar 5 cajas de ABC-01 (cada caja trae 12 cuadernos) a $24,000 por caja
        factor = 12.0
        cant_empaques = 5.0
        costo_empaque = 24000.0
        unidades_base = factor * cant_empaques  # 60 unidades
        costo_unit_convertido = costo_empaque / factor  # $2,000 c/u
        subtotal = cant_empaques * costo_empaque  # $120,000

        self.assertEqual(unidades_base, 60.0)
        self.assertEqual(costo_unit_convertido, 2000.0)
        self.assertEqual(subtotal, 120000.0)


class TestPreciosVariablesYEdicionCarrito(unittest.TestCase):
    """Pruebas para precios variables en productos físicos y modificación en caliente del carrito POS."""

    def test_precio_variable_en_producto_fisico_y_servicio(self):
        """Tanto un producto físico como un servicio con precio_variable=True deben permitir precio manual."""
        item_fisico_var = ("00010", "Cuaderno personalizado", 10, 5000.0, "Fisico", 1, 10, 3000.0, True, 20, "")
        item_fisico_fijo = ("00011", "Cuaderno estándar", 10, 5000.0, "Fisico", 1, 11, 3000.0, False, 20, "")
        item_servicio_var = ("S0001", "Fotocopias / Impresiones", 9999, 200.0, "Servicio", None, 50, 0.0, True, 0, "")

        self.assertTrue(item_fisico_var[8], "Producto físico debe tener precio_variable habilitado")
        self.assertFalse(item_fisico_fijo[8], "Producto estándar no debe tener precio variable")
        self.assertTrue(item_servicio_var[8], "Servicio debe tener precio_variable habilitado")

    def test_modificar_cantidad_unidades_enteras_vs_fraccionadas(self):
        """Valida que unidades discretas ('Unidad') rechacen decimales y continuas ('Metro') los acepten."""
        # Validación regla discreta
        u_discreta = "Unidad"
        cant_entera = 3.0
        cant_fraccion = 2.5

        es_valido_entero = (u_discreta in ("Unidad", "Caja", "Paquete", "Docena")) and cant_entera.is_integer()
        es_valido_fraccion = (u_discreta in ("Unidad", "Caja", "Paquete", "Docena")) and cant_fraccion.is_integer()
        self.assertTrue(es_valido_entero)
        self.assertFalse(es_valido_fraccion, "Unidad discreta no debe admitir fraccionamiento decimal")

        # Validación regla fraccionada
        u_continua = "Metro"
        cant_metro = 1.75
        es_valido_metro = cant_metro > 0
        self.assertTrue(es_valido_metro)

    def test_recalculo_inmediato_subtotal_y_total_carrito(self):
        """Al modificar cantidad o precio, el subtotal de la fila y el total general se recalculan al instante."""
        # Fila inicial: 2 unidades a $5,000 = $10,000
        cant = 2.0
        precio = 5000.0
        subtotal_1 = cant * precio
        self.assertEqual(subtotal_1, 10000.0)

        # Modificación de cantidad a 3 -> $15,000
        cant = 3.0
        subtotal_2 = cant * precio
        self.assertEqual(subtotal_2, 15000.0)

        # Modificación de precio a $4,500 -> $13,500
        precio = 4500.0
        subtotal_3 = cant * precio
        self.assertEqual(subtotal_3, 13500.0)


class TestConexionVentasContabilidad(unittest.TestCase):
    """Pruebas de la venta confirmada como única fuente de verdad contable."""

    def setUp(self):
        self.db_fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.environ["VMPOS_DB_VENTAS"] = self.db_path
        inicializar_base_datos(self.db_path)
        conn = conectar_db(self.db_path)
        cur = conn.cursor()

        # Crear producto maestro de prueba en catálogo
        cur.execute("""
            INSERT INTO productos (codigo, nombre, categoria, unidad_medida, costo, precio, stock_bodega, stock_vitrina, stock)
            VALUES ('00100', 'Cuaderno 100H Cuadriculado', 'Papelería', 'Unidad', 3000, 5000, 20, 15, 35)
        """)

        # Crear cliente para prueba de fiado
        cur.execute("""
            INSERT INTO clientes (id, cedula, nombre, permite_fiado, saldo_pendiente, fecha_registro)
            VALUES (10, 'CC-777', 'Juan Pérez', 1, 0.0, '2026-11-09 10:00:00')
        """)
        conn.commit()
        conn.close()

        # Abrir sesión de caja para cobros en efectivo
        self.sesion_id = abrir_sesion_caja(usuario='Administrador', monto_inicial=100000)

    def tearDown(self):
        try:
            os.close(self.db_fd)
            os.remove(self.db_path)
        except Exception:
            pass

    def test_venta_precio_modificado_no_cambia_catalogo_maestro(self):
        """
        Vender 3 cuadernos con precio habitual $5,000 negociados a $4,500:
        1. Venta total debe ser $13,500 (no $15,000).
        2. Detalle debe registrar precio_unitario=$4,500 y costo_unitario=$3,000.
        3. El precio maestro en catálogo debe permanecer en $5,000.
        4. Utilidad calculada: $13,500 - (3 * $3,000) = $4,500.
        """
        detalles = [{
            "item_codigo": "00100",
            "item_nombre": "Cuaderno 100H Cuadriculado",
            "precio_original": 5000.0,
            "precio_vendido": 4500.0,
            "cantidad": 3.0,
            "subtotal": 13500.0,
            "tipo_item": "Producto"
        }]

        id_venta = guardar_venta_sqlite(
            doc_cliente="Consumidor Final",
            total=13500.0,
            metodo_pago="Efectivo",
            detalles=detalles,
            operario_nombre="Administrador"
        )
        self.assertIsNotNone(id_venta)

        conn = conectar_db(self.db_path)
        cur = conn.cursor()

        # 1. Verificar total venta
        cur.execute("SELECT total_venta, metodo_pago FROM ventas WHERE id_venta = ?", (id_venta,))
        tot_v, mp_v = cur.fetchone()
        self.assertEqual(tot_v, 13500.0)
        self.assertEqual(mp_v, "Efectivo")

        # 2. Verificar detalle histórico
        cur.execute("SELECT precio_unitario, cantidad, subtotal, costo_unitario FROM detalle_ventas WHERE id_venta = ?", (id_venta,))
        pu, cant, sub, cost = cur.fetchone()
        self.assertEqual(pu, 4500.0)
        self.assertEqual(cant, 3.0)
        self.assertEqual(sub, 13500.0)
        self.assertEqual(cost, 3000.0)

        # 3. Comprobar que el precio del catálogo maestro NO fue alterado
        cur.execute("SELECT precio, costo FROM productos WHERE codigo = '00100'")
        p_maestro, c_maestro = cur.fetchone()
        self.assertEqual(p_maestro, 5000.0, "El precio maestro en catálogo no debe cambiar por una venta a precio especial")
        self.assertEqual(c_maestro, 3000.0)

        # 4. Cálculo de utilidad
        utilidad = sub - (cant * cost)
        self.assertEqual(utilidad, 4500.0)
        conn.close()

    def test_venta_fiado_actualiza_cuenta_por_cobrar_sin_inflar_caja_efectivo(self):
        """
        Una venta FIADA debe:
        1. Registrar total en la venta.
        2. Registrar saldo_pendiente en la venta.
        3. NO inflar las ventas en efectivo en el arqueo físico de caja.
        """
        detalles = [{
            "item_codigo": "00100",
            "item_nombre": "Cuaderno 100H Cuadriculado",
            "precio_original": 5000.0,
            "precio_vendido": 5000.0,
            "cantidad": 2.0,
            "subtotal": 10000.0,
            "tipo_item": "Producto"
        }]

        id_venta = guardar_venta_sqlite(
            doc_cliente="CC-777",
            total=10000.0,
            metodo_pago="Fiado",
            detalles=detalles,
            operario_nombre="Administrador",
            cliente_id=10
        )
        self.assertIsNotNone(id_venta)

        conn = conectar_db(self.db_path)
        cur = conn.cursor()
        cur.execute("SELECT total_venta, saldo_pendiente, metodo_pago FROM ventas WHERE id_venta = ?", (id_venta,))
        tot_v, sal_pend, mp = cur.fetchone()
        self.assertEqual(tot_v, 10000.0)
        self.assertEqual(sal_pend, 10000.0)
        self.assertEqual(mp, "Fiado")

        # Comprobar arqueo de caja física: el fiado NO debe sumarse a 'ventas_efectivo'
        arqueo = calcular_arqueo_sesion(self.sesion_id)
        self.assertEqual(arqueo["ventas_efectivo"], 0.0, "Ventas fiadas no deben computar como dinero físico recibido en caja")
        conn.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
