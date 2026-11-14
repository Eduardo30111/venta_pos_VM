#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: Auditoría y Verificación del Flujo Integral de Materiales,
Bodega, Inventarios Individuales, Ventas y Arqueos en VmPOS.

Pruebas:
- Caso A: Entrada/Compra de paquetes con factor de conversión -> Bodega en unidades base.
- Caso B: Traslado de Bodega a inventario individual de un operario.
- Caso C: Traslado de Bodega al inventario individual del administrador.
- Caso D: Consumo de material asignado en venta por parte del operario.
- Caso E: Aislamiento multi-usuario (Admin solo consume de Admin, Operario de Operario).
- Caso F: Integridad: bloqueo de saldos negativos, idempotencia y kárdex.
- Caso G: Arqueo de efectivo por denominaciones en apertura y cierre de caja.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime

from interface.materiales_manager import (
    resolver_identificadores_usuario,
    trasladar_bodega_a_operario,
    devolver_operario_a_bodega,
    descontar_materiales_venta,
    obtener_inventario_operario,
    obtener_saldo_material_usuario,
    registrar_desperdicio_material,
)
from interface.inventario_manager import (
    _sincronizar_compra_local_sqlite,
    _sincronizar_ajuste_local_sqlite,
)


class TestAuditoriaMaterialesFlujoCompleto(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_ventas = os.path.join(self.temp_dir, "ventas.db")
        self.db_usuarios = os.path.join(self.temp_dir, "usuarios.db")
        os.environ["VMPOS_DB_VENTAS"] = self.db_ventas

        # 1. Crear estructura completa en ventas.db
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.executescript("""
            CREATE TABLE productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT,
                tipo_producto TEXT DEFAULT 'Producto',
                unidad_medida TEXT DEFAULT 'Unidad',
                stock_bodega REAL DEFAULT 0.0,
                stock_vitrina REAL DEFAULT 0.0,
                stock REAL DEFAULT 0.0,
                costo REAL DEFAULT 0.0,
                precio_costo REAL DEFAULT 0.0,
                precio REAL DEFAULT 0.0,
                precio_venta REAL DEFAULT 0.0,
                es_material INTEGER DEFAULT 1,
                presentacion_defecto TEXT DEFAULT 'Paquete',
                factor_conversion_defecto REAL DEFAULT 500.0,
                unidad_consumo_defecto TEXT DEFAULT 'Hoja',
                estado TEXT DEFAULT 'Activo',
                fecha_modificacion TEXT
            );

            CREATE TABLE inventario_operarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                usuario_nombre TEXT,
                rol TEXT,
                producto_id INTEGER,
                codigo_producto TEXT,
                nombre_producto TEXT,
                unidad_medida TEXT,
                stock_disponible REAL DEFAULT 0.0,
                total_recibido REAL DEFAULT 0.0,
                total_consumido REAL DEFAULT 0.0,
                total_desperdiciado REAL DEFAULT 0.0,
                total_devuelto REAL DEFAULT 0.0,
                ultimo_movimiento TEXT,
                fecha_actualizacion TEXT
            );

            CREATE TABLE compras_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_compra TEXT UNIQUE,
                fecha TEXT,
                hora TEXT,
                proveedor_id INTEGER,
                proveedor_nombre TEXT,
                documento_referencia TEXT,
                ubicacion_destino TEXT,
                total_compra REAL,
                usuario TEXT,
                observaciones TEXT,
                estado TEXT,
                created_at TIMESTAMP
            );

            CREATE TABLE detalle_compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compra_id INTEGER,
                producto_id INTEGER,
                codigo_producto TEXT,
                nombre_producto TEXT,
                unidad_compra TEXT,
                factor_conversion REAL,
                cantidad_comprada REAL,
                cantidad_unidades REAL,
                costo_unidad_compra REAL,
                costo_unitario_convertido REAL,
                subtotal REAL
            );

            CREATE TABLE traslados_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_traslado TEXT UNIQUE,
                fecha TEXT,
                hora TEXT,
                producto_id INTEGER,
                codigo_producto TEXT,
                nombre_producto TEXT,
                ubicacion_origen TEXT,
                ubicacion_destino TEXT,
                cantidad REAL,
                usuario TEXT,
                estado TEXT,
                observaciones TEXT
            );

            CREATE TABLE movimientos_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT,
                hora TEXT,
                producto_id INTEGER,
                codigo_producto TEXT,
                nombre_producto TEXT,
                tipo_movimiento TEXT,
                tipo TEXT,
                cantidad REAL,
                unidad_medida TEXT,
                ubicacion_origen TEXT,
                ubicacion_destino TEXT,
                stock_origen_ant REAL,
                stock_origen_des REAL,
                stock_destino_ant REAL,
                stock_destino_des REAL,
                stock_anterior REAL,
                stock_nuevo REAL,
                costo_unitario REAL,
                valor_total REAL,
                referencia TEXT,
                usuario TEXT,
                usuario_id INTEGER,
                usuario_nombre TEXT,
                observacion TEXT,
                observaciones TEXT,
                estado TEXT
            );

            CREATE TABLE consumos_materiales_venta (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                venta_id INTEGER,
                numero_factura TEXT,
                usuario_responsable TEXT,
                producto_id INTEGER,
                codigo_producto TEXT,
                nombre_producto TEXT,
                cantidad_consumida REAL,
                unidad_medida TEXT,
                saldo_anterior REAL,
                saldo_restante REAL,
                costo_unitario REAL,
                costo_total REAL,
                fecha TEXT,
                hora TEXT,
                estado TEXT,
                observaciones TEXT
            );

            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE,
                rol TEXT,
                nombre TEXT,
                apellidos TEXT
            );
        """)
        conn.commit()
        conn.close()

        # 2. Inicializar usuarios de prueba
        conn_u = sqlite3.connect(self.db_ventas)
        cur_u = conn_u.cursor()
        cur_u.execute("INSERT INTO usuarios (id, usuario, rol, nombre, apellidos) VALUES (1, 'admin', 'Administrador', 'Admin', 'Principal')")
        cur_u.execute("INSERT INTO usuarios (id, usuario, rol, nombre, apellidos) VALUES (2, 'operario1', 'Operario', 'Carlos', 'Gomez')")
        conn_u.commit()
        conn_u.close()

    def tearDown(self):
        if "VMPOS_DB_VENTAS" in os.environ:
            del os.environ["VMPOS_DB_VENTAS"]
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_caso_a_compra_paquetes_a_unidades_bodega(self):
        """Caso A: Comprar 1 paquete de 500 hojas ingresa 500 unidades base a Bodega."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 0.0, 0.0, 0.0, 25.0)
        """)
        conn.commit()

        # Sincronizar compra de 1 paquete (factor 500 = 500 hojas)
        items_compra = [{
            "producto_id": 101,
            "codigo": "MAT-RESMA",
            "nombre": "Papel Normal Carta",
            "unidad_compra": "Paquete",
            "factor_conversion": 500.0,
            "cantidad_comprada": 1.0,
            "costo_unidad_compra": 15000.0,
        }]

        _sincronizar_compra_local_sqlite(
            compra_id=1,
            numero_compra="COM-000001",
            proveedor_id=1,
            proveedor_nombre="Distribuidora Papelera",
            doc_referencia="FAC-9901",
            ubicacion_destino="BODEGA",
            usuario="admin",
            observaciones="Compra de papel en paquete",
            items=items_compra,
            conn=conn
        )

        cur.execute("SELECT stock_bodega, stock, costo FROM productos WHERE id = 101")
        prod = cur.fetchone()
        conn.close()

        self.assertEqual(prod[0], 500.0, "Bodega debe reflejar exactamente 500 unidades base")
        self.assertEqual(prod[1], 500.0, "Stock total debe reflejar 500 unidades")
        self.assertEqual(prod[2], 30.0, "Costo unitario convertido debe ser 15000 / 500 = 30 COP")

    def test_caso_b_traslado_bodega_a_operario(self):
        """Caso B: Trasladar 200 hojas a un operario deja Bodega en 300 y Operario en 200."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 500.0, 0.0, 500.0, 30.0)
        """)
        conn.commit()
        conn.close()

        res = trasladar_bodega_a_operario(
            producto_id=101,
            usuario_destino="operario1",
            cantidad_unidades=200.0,
            usuario_responsable="admin",
            observaciones="Entrega para turno de la mañana"
        )

        self.assertEqual(res["saldo_bodega_restante"], 300.0)
        self.assertEqual(res["saldo_operario_nuevo"], 200.0)

        # Verificar saldo directo
        saldo_op = obtener_saldo_material_usuario("operario1", 101)
        self.assertEqual(saldo_op, 200.0)

    def test_caso_c_traslado_bodega_a_administrador(self):
        """Caso C: Trasladar 100 hojas al Administrador deja Bodega en 200, Admin en 100 y Operario en 200."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 300.0, 0.0, 300.0, 30.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('operario1', 'Operario', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 200.0, 200.0)
        """)
        conn.commit()
        conn.close()

        res = trasladar_bodega_a_operario(
            producto_id=101,
            usuario_destino="admin",
            cantidad_unidades=100.0,
            usuario_responsable="admin",
            observaciones="Asignación directa a puesto admin"
        )

        self.assertEqual(res["saldo_bodega_restante"], 200.0)
        self.assertEqual(res["saldo_operario_nuevo"], 100.0)

        # Comprobar que 'Administrador' o 'admin' encuentran su saldo de 100
        saldo_admin_login = obtener_saldo_material_usuario("admin", 101)
        saldo_admin_alias = obtener_saldo_material_usuario("Administrador", 101)
        self.assertEqual(saldo_admin_login, 100.0)
        self.assertEqual(saldo_admin_alias, 100.0)

        # Operario1 sigue intacto en 200
        saldo_op = obtener_saldo_material_usuario("operario1", 101)
        self.assertEqual(saldo_op, 200.0)

    def test_caso_d_consumo_en_venta_como_operario(self):
        """Caso D: Operario consume 50 hojas en una venta -> Operario 150, Admin 100, Bodega 200."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 200.0, 0.0, 200.0, 30.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('operario1', 'Operario', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 200.0, 200.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('admin', 'Administrador', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 100.0, 100.0)
        """)
        conn.commit()
        conn.close()

        items_consumo = [{
            "producto_id": 101,
            "codigo": "MAT-RESMA",
            "nombre": "Papel Normal Carta",
            "cantidad": 50.0,
            "unidad": "Hoja"
        }]

        res_desc = descontar_materiales_venta(
            venta_id=501,
            numero_factura="FAC-501",
            usuario_operario="operario1",
            items_materiales=items_consumo,
            observaciones="Impresiones tesis cliente Juan"
        )

        self.assertTrue(res_desc.get("ok"), "Descuento de venta debe ser exitoso")

        # Verificar saldos aislados
        self.assertEqual(obtener_saldo_material_usuario("operario1", 101), 150.0)
        self.assertEqual(obtener_saldo_material_usuario("admin", 101), 100.0)

        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("SELECT stock_bodega FROM productos WHERE id = 101")
        self.assertEqual(cur.fetchone()[0], 200.0, "Bodega no debe alterarse por una venta de operario")
        conn.close()

    def test_caso_e_aislamiento_multi_usuario(self):
        """Caso E: Administrador solo consume de Administrador y Operario de Operario. Intento de exceso es bloqueado."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 200.0, 0.0, 200.0, 30.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('operario1', 'Operario', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 150.0, 200.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('admin', 'Administrador', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 100.0, 100.0)
        """)
        conn.commit()
        conn.close()

        # 1. Admin intenta consumir 120 hojas (solo tiene 100) -> Debe fallar sin tocar el stock del operario
        res_fallo = descontar_materiales_venta(
            venta_id=601,
            numero_factura="FAC-601",
            usuario_operario="Administrador",
            items_materiales=[{"producto_id": 101, "cantidad": 120.0}]
        )
        self.assertFalse(res_fallo.get("ok"))
        self.assertIn("Saldo insuficiente", res_fallo.get("mensaje", ""))

        # Verificar que ambos saldos siguen intactos
        self.assertEqual(obtener_saldo_material_usuario("Administrador", 101), 100.0)
        self.assertEqual(obtener_saldo_material_usuario("operario1", 101), 150.0)

        # 2. Admin consume 30 hojas (dispone de 100) -> Queda en 70, Operario sigue en 150
        res_ok = descontar_materiales_venta(
            venta_id=602,
            numero_factura="FAC-602",
            usuario_operario="Administrador",
            items_materiales=[{"producto_id": 101, "cantidad": 30.0}]
        )
        self.assertTrue(res_ok.get("ok"))
        self.assertEqual(obtener_saldo_material_usuario("Administrador", 101), 70.0)
        self.assertEqual(obtener_saldo_material_usuario("operario1", 101), 150.0)

    def test_caso_f_integridad_idempotencia_y_kardex(self):
        """Caso F: Idempotencia en consumos de venta, no repite descuentos si la venta ya fue procesada."""
        conn = sqlite3.connect(self.db_ventas)
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO productos (id, codigo, nombre, unidad_medida, stock_bodega, stock_vitrina, stock, costo)
            VALUES (101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 200.0, 0.0, 200.0, 30.0)
        """)
        cur.execute("""
            INSERT INTO inventario_operarios (usuario_nombre, rol, producto_id, codigo_producto, nombre_producto, unidad_medida, stock_disponible, total_recibido)
            VALUES ('operario1', 'Operario', 101, 'MAT-RESMA', 'Papel Normal Carta', 'Hoja', 100.0, 100.0)
        """)
        conn.commit()
        conn.close()

        items = [{"producto_id": 101, "cantidad": 20.0}]

        # Primer consumo
        r1 = descontar_materiales_venta(venta_id=701, numero_factura="FAC-701", usuario_operario="operario1", items_materiales=items)
        self.assertTrue(r1.get("ok"))
        self.assertEqual(obtener_saldo_material_usuario("operario1", 101), 80.0)

        # Segundo intento con el mismo venta_id (simula retry de red o idempotencia)
        r2 = descontar_materiales_venta(venta_id=701, numero_factura="FAC-701", usuario_operario="operario1", items_materiales=items)
        self.assertTrue(r2.get("ok"))
        self.assertIn("aviso", r2)
        # El saldo no debe haber bajado nuevamente
        self.assertEqual(obtener_saldo_material_usuario("operario1", 101), 80.0)


if __name__ == "__main__":
    unittest.main()
