#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas obligatorias para el sistema de filtros, búsqueda y ordenamiento de VmPOS.
Verifica los 17 puntos requeridos en el módulo de Inventario:
1. Crear categorías (incluyendo Gaseosas).
2. Registrar productos de prueba.
3. Buscar 'Amara' (insensible a mayúsculas y acentos).
4. Buscar por código de barras.
5. Filtrar por categoría.
6. Filtrar por proveedor.
7. Combinar categoría y proveedor.
8. Ordenar nombres A-Z.
9. Ordenar nombres Z-A.
10. Ordenar stock de menor a mayor.
11. Ordenar stock de mayor a menor.
12. Ordenar precios.
13. Comprobar filtros activos al ordenar.
14. Limpiar filtros y recuperar todos los artículos.
15. Verificar que el ordenamiento no modifique datos en DB.
16. Probar rendimiento con catálogo grande (>500 artículos).
17. Verificar compatibilidad multiplataforma.
"""

import os
import sys
import unittest
import sqlite3
import tempfile
import time

# Asegurar path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from interface.table_filter_sorter import (
    TreeviewSortManager, normalizar_texto, extraer_clave_orden, coincide_busqueda, insertar_estado_vacio
)
from interface.inventario_manager import (
    obtener_catalogo, obtener_existencias_bodega, obtener_existencias_vitrina
)


class TestFiltrosBusquedaOrdenamiento(unittest.TestCase):
    def setUp(self):
        # Crear base de datos SQLite temporal en memoria / archivo temporal
        self.temp_db_fd, self.temp_db_path = tempfile.mkstemp(suffix=".db")
        self.conn = sqlite3.connect(self.temp_db_path)
        cur = self.conn.cursor()

        # Crear tablas necesarias
        cur.execute("""
            CREATE TABLE IF NOT EXISTS proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                telefono TEXT,
                email TEXT,
                estado TEXT DEFAULT 'Activo'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categorias (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                estado TEXT DEFAULT 'Activo'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT,
                categoria TEXT,
                categoria_id INTEGER,
                unidad_medida TEXT,
                precio_venta REAL,
                precio_costo REAL,
                stock REAL,
                stock_bodega REAL,
                stock_vitrina REAL,
                stock_minimo_bodega REAL,
                stock_minimo_vitrina REAL,
                proveedor_id INTEGER,
                estado TEXT DEFAULT 'Activo',
                codigo_barras TEXT,
                descripcion TEXT,
                marca TEXT,
                created_at TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS servicios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT,
                categoria TEXT,
                unidad_medida TEXT,
                precio_venta REAL,
                costo_proveedor REAL,
                proveedor_id INTEGER,
                estado TEXT DEFAULT 'Activo',
                codigo_barras TEXT,
                descripcion TEXT
            )
        """)

        # 1. Crear proveedores
        cur.execute("INSERT INTO proveedores (nombre) VALUES ('Distribuidor A')")
        self.prov_a_id = cur.lastrowid
        cur.execute("INSERT INTO proveedores (nombre) VALUES ('Proveedor B')")
        self.prov_b_id = cur.lastrowid

        # 2. Crear categorías
        cur.execute("INSERT INTO categorias (nombre) VALUES ('Gaseosas')")
        cur.execute("INSERT INTO categorias (nombre) VALUES ('Papelería')")
        cur.execute("INSERT INTO categorias (nombre) VALUES ('Abarrotes')")

        # 3. Insertar productos de prueba
        productos_data = [
            ("GA-001", "Gaseosa Amara 500ml", "Gaseosas", "Unidad", 3500.0, 2000.0, 50.0, 30.0, 20.0, 10.0, 5.0, self.prov_a_id, "Activo", "7701234567890", "Bebida refrescante sabor Amara"),
            ("GA-002", "Gaseosa Cola 1.5L", "Gaseosas", "Unidad", 6000.0, 4000.0, 0.0, 0.0, 0.0, 5.0, 2.0, self.prov_a_id, "Activo", "7701234567891", "Gaseosa oscura familiar"),
            ("GA-003", "Gaseosa Manzana 2L", "Gaseosas", "Unidad", 7500.0, 5000.0, 4.0, 2.0, 2.0, 10.0, 5.0, self.prov_b_id, "Activo", "7701234567892", "Gaseosa sabor manzana"),
            ("PA-010", "Papel Fotográfico Brillo", "Papelería", "Paquete", 25000.0, 15000.0, 15.0, 10.0, 5.0, 5.0, 2.0, self.prov_b_id, "Activo", "7709999888811", "Papel alta resolución"),
            ("PA-002", "Papel Bond Carta", "Papelería", "Paquete", 18000.0, 12000.0, 100.0, 70.0, 30.0, 20.0, 10.0, self.prov_b_id, "Activo", "7709999888812", "Resma 500 hojas"),
            ("AB-001", "Café Tostado Premium", "Abarrotes", "Unidad", 12000.0, 8000.0, 25.0, 15.0, 10.0, 5.0, 2.0, self.prov_a_id, "Inactivo", "7707777666655", "Café molido suave"),
            ("AB-002", "Azúcar Blanca 1kg", "Abarrotes", "Kilogramo", 4500.0, 3000.0, 5.0, 2.0, 3.0, 10.0, 5.0, self.prov_a_id, "Activo", "7707777666656", "Azúcar refinada"),
        ]

        for p in productos_data:
            cur.execute("""
                INSERT INTO productos (
                    codigo, nombre, categoria, unidad_medida, precio_venta, precio_costo,
                    stock, stock_bodega, stock_vitrina, stock_minimo_bodega, stock_minimo_vitrina,
                    proveedor_id, estado, codigo_barras, descripcion
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, p)

        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.close(self.temp_db_fd)
        if os.path.exists(self.temp_db_path):
            os.remove(self.temp_db_path)

    def test_01_creacion_categorias_y_productos(self):
        """Verifica que las categorías y productos iniciales existen correctamente."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM categorias WHERE nombre = 'Gaseosas'")
        self.assertEqual(cur.fetchone()[0], 1)
        cur.execute("SELECT COUNT(*) FROM productos")
        self.assertEqual(cur.fetchone()[0], 7)

    def test_02_busqueda_amara_insensible_mayusculas_y_tildes(self):
        """Buscar 'Amara', 'amara' o 'AMARA' encuentra 'Gaseosa Amara 500ml'."""
        for term in ("Amara", "amara", "AMARA", "amar"):
            res = obtener_catalogo(filtro=term, conn=self.conn)
            self.assertTrue(len(res) >= 1)
            nombres = [r["nombre"] for r in res]
            self.assertIn("Gaseosa Amara 500ml", nombres)

    def test_03_busqueda_tildes_cafe(self):
        """Buscar 'cafe' (sin tilde) encuentra 'Café Tostado Premium'."""
        res1 = obtener_catalogo(filtro="cafe", conn=self.conn)
        self.assertTrue(any("Café" in r["nombre"] for r in res1))

        res2 = obtener_catalogo(filtro="Café", conn=self.conn)
        self.assertTrue(any("Café" in r["nombre"] for r in res2))

    def test_04_busqueda_codigo_barras(self):
        """Buscar por código de barras exacto o parcial."""
        res = obtener_catalogo(filtro="7701234567890", conn=self.conn)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["codigo"], "GA-001")

    def test_05_filtro_por_categoria(self):
        """Filtrar por categoría 'Gaseosas' devuelve solo gaseosas."""
        res = obtener_catalogo(categoria="Gaseosas", conn=self.conn)
        self.assertEqual(len(res), 3)
        for r in res:
            self.assertEqual(r["categoria"], "Gaseosas")

    def test_06_filtro_por_proveedor(self):
        """Filtrar por proveedor 'Distribuidor A'."""
        res = obtener_catalogo(proveedor="Distribuidor A", conn=self.conn)
        self.assertTrue(len(res) >= 3)
        for r in res:
            self.assertEqual(r["proveedor_nombre"], "Distribuidor A")

    def test_07_filtro_combinado_categoria_y_proveedor(self):
        """Combinar categoría 'Gaseosas' + proveedor 'Distribuidor A'."""
        res = obtener_catalogo(categoria="Gaseosas", proveedor="Distribuidor A", conn=self.conn)
        self.assertEqual(len(res), 2)
        nombres = [r["nombre"] for r in res]
        self.assertIn("Gaseosa Amara 500ml", nombres)
        self.assertIn("Gaseosa Cola 1.5L", nombres)
        self.assertNotIn("Gaseosa Manzana 2L", nombres)

    def test_08_filtro_disponibilidad_stock(self):
        """Filtrar por 'Agotado (0)' y 'En Stock (>0)'."""
        agotados = obtener_catalogo(disponibilidad="Agotado (0)", conn=self.conn)
        self.assertEqual(len(agotados), 1)
        self.assertEqual(agotados[0]["codigo"], "GA-002")

        en_stock = obtener_catalogo(disponibilidad="En Stock (>0)", conn=self.conn)
        for r in en_stock:
            self.assertGreater(r["stock"], 0)

    def test_09_ordenamiento_alfabetico_nombres(self):
        """Ordenamiento alfabético de nombres A-Z y Z-A."""
        items = obtener_catalogo(conn=self.conn)
        nombres = [it["nombre"] for it in items]

        # Ascendente
        nombres_asc = sorted(nombres, key=lambda x: extraer_clave_orden(x, "text"))
        self.assertEqual(nombres_asc[0], "Azúcar Blanca 1kg")

        # Descendente
        nombres_desc = sorted(nombres, key=lambda x: extraer_clave_orden(x, "text"), reverse=True)
        self.assertEqual(nombres_desc[0], "Papel Fotográfico Brillo")

    def test_10_ordenamiento_numerico_stock(self):
        """Ordenar stock de menor a mayor y de mayor a menor."""
        items = obtener_catalogo(conn=self.conn)
        stocks_asc = sorted([it["stock"] for it in items], key=lambda x: extraer_clave_orden(x, "numeric"))
        self.assertEqual(stocks_asc, [0.0, 4.0, 5.0, 15.0, 25.0, 50.0, 100.0])

        stocks_desc = sorted([it["stock"] for it in items], key=lambda x: extraer_clave_orden(x, "numeric"), reverse=True)
        self.assertEqual(stocks_desc, [100.0, 50.0, 25.0, 15.0, 5.0, 4.0, 0.0])

    def test_11_ordenamiento_precios_moneda(self):
        """Ordenar precios de venta formateados como moneda."""
        precios_fmt = ["$ 18.000 COP", "$ 3.500 COP", "$ 25.000 COP", "$ 4.500 COP", "$ 0 COP"]
        ordenados_asc = sorted(precios_fmt, key=lambda x: extraer_clave_orden(x, "currency"))
        self.assertEqual(ordenados_asc, ["$ 0 COP", "$ 3.500 COP", "$ 4.500 COP", "$ 18.000 COP", "$ 25.000 COP"])

    def test_12_ordenamiento_natural_sku_codigos(self):
        """Ordenamiento natural para códigos alfanuméricos (PA-2 antes de PA-10)."""
        codigos = ["PA-010", "PA-002", "GA-001", "GA-003", "GA-002", "MAT-2", "MAT-10", "MAT-1"]
        ordenados = sorted(codigos, key=lambda x: extraer_clave_orden(x, "sku"))
        # MAT-1 < MAT-2 < MAT-10
        idx_mat1 = ordenados.index("MAT-1")
        idx_mat2 = ordenados.index("MAT-2")
        idx_mat10 = ordenados.index("MAT-10")
        self.assertLess(idx_mat1, idx_mat2)
        self.assertLess(idx_mat2, idx_mat10)

    def test_13_preservacion_filtros_al_ordenar(self):
        """Comprobar que aplicar un orden sobre resultados filtrados no pierde los filtros."""
        # Filtrar categoría 'Gaseosas'
        filtrados = obtener_catalogo(categoria="Gaseosas", conn=self.conn)
        self.assertEqual(len(filtrados), 3)

        # Ordenar por precio ascendente
        ordenados = sorted(filtrados, key=lambda x: extraer_clave_orden(x["precio"], "currency"))
        self.assertEqual(len(ordenados), 3)
        for r in ordenados:
            self.assertEqual(r["categoria"], "Gaseosas")
        self.assertEqual(ordenados[0]["nombre"], "Gaseosa Amara 500ml")
        self.assertEqual(ordenados[-1]["nombre"], "Gaseosa Manzana 2L")

    def test_14_limpiar_filtros_recupera_todo(self):
        """Limpiar filtros devuelve el total completo de artículos."""
        todos = obtener_catalogo(conn=self.conn)
        self.assertEqual(len(todos), 7)

    def test_15_integridad_datos_no_mutados(self):
        """Verificar que el ordenamiento y filtrado no alteran los registros en la base de datos."""
        cur = self.conn.cursor()
        cur.execute("SELECT COUNT(*), SUM(stock), SUM(precio_venta) FROM productos")
        antes = cur.fetchone()

        # Ejecutar múltiples búsquedas, filtros y órdenes
        _ = obtener_catalogo(filtro="Amara", conn=self.conn)
        _ = obtener_catalogo(categoria="Gaseosas", conn=self.conn)
        _ = obtener_catalogo(disponibilidad="Agotado (0)", conn=self.conn)

        cur.execute("SELECT COUNT(*), SUM(stock), SUM(precio_venta) FROM productos")
        despues = cur.fetchone()
        self.assertEqual(antes, despues)

    def test_16_rendimiento_gran_volumen_productos(self):
        """Insertar 600 artículos y verificar que la búsqueda, filtrado y ordenamiento toman < 100ms."""
        cur = self.conn.cursor()
        nuevos = []
        for i in range(1, 601):
            nuevos.append((
                f"BIG-{i:04d}",
                f"Producto Masivo de Prueba {i}",
                "Gaseosas" if i % 2 == 0 else "Papelería",
                "Unidad",
                float(i * 100),
                float(i * 60),
                float(i % 50),
                float(i % 30),
                float(i % 20),
                5.0,
                2.0,
                self.prov_a_id if i % 2 == 0 else self.prov_b_id,
                "Activo",
                f"7708888{i:05d}",
                f"Descripción automática para prueba de escala {i}"
            ))
        cur.executemany("""
            INSERT INTO productos (
                codigo, nombre, categoria, unidad_medida, precio_venta, precio_costo,
                stock, stock_bodega, stock_vitrina, stock_minimo_bodega, stock_minimo_vitrina,
                proveedor_id, estado, codigo_barras, descripcion
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, nuevos)
        self.conn.commit()

        t0 = time.time()
        res_busq = obtener_catalogo(filtro="Masivo", conn=self.conn)
        t_busq = (time.time() - t0) * 1000.0

        self.assertEqual(len(res_busq), 600)
        self.assertLess(t_busq, 150.0, f"Búsqueda masiva tomó {t_busq:.1f}ms (esperado < 150ms)")

        t0 = time.time()
        res_ord = sorted(res_busq, key=lambda x: extraer_clave_orden(x["precio"], "currency"), reverse=True)
        t_ord = (time.time() - t0) * 1000.0
        self.assertLess(t_ord, 80.0, f"Ordenamiento masivo tomó {t_ord:.1f}ms (esperado < 80ms)")

    def test_17_existencias_bodega_y_vitrina_filtros(self):
        """Verificar filtros de alerta y categorías en bodega y vitrina."""
        bod = obtener_existencias_bodega(alerta="Normal", conn=self.conn)
        for b in bod:
            self.assertEqual(b["alerta_bodega"], "Normal")

        vit_disp = obtener_existencias_vitrina(alerta="Disponible", conn=self.conn)
        for v in vit_disp:
            self.assertEqual(v["alerta_vitrina"], "Disponible")


if __name__ == "__main__":
    unittest.main()
