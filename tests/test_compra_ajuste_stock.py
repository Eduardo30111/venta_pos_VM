#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test de verificación de flujo completo:
1. Entrada / Compra de mercancía (ej. 15 paquetes x 500 unidades = 7.500 unidades).
2. Reflejo inmediato en existencias de Bodega / Vitrina.
3. Ajuste de conteo físico en Bodega.
4. Traslado de Bodega a inventario individual de trabajador.
5. Verificación de integridad en Kárdex (movimientos_inventario) sin errores 500 ni OperationalError.
"""

import asyncio
import os
import sqlite3
import unittest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.future import select

from server.database import Base, asegurar_migraciones_sqlite
from server.models.producto import Producto
from server.models.inventario import MovimientoInventario, CompraInventario, DetalleCompra
from server.models.usuario import Usuario
from server.models.proveedor import Proveedor
from server.routers.inventario_central import registrar_compra_endpoint, registrar_ajuste_endpoint
from server.schemas.inventario import CompraCreate, ItemCompraCreate, AjusteInventarioCreate
from interface.materiales_manager import trasladar_bodega_a_operario


class TestCompraAjusteStockFlow(unittest.TestCase):
    def setUp(self):
        self.db_path = "/tmp/test_compra_ajuste_flow.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

        # Crear esquema base
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE,
                nombre TEXT,
                descripcion TEXT,
                categoria_id INTEGER,
                categoria TEXT DEFAULT 'General',
                marca TEXT DEFAULT '',
                unidad_medida TEXT DEFAULT 'Unidad',
                precio_costo REAL DEFAULT 0.0,
                costo REAL DEFAULT 0.0,
                precio_venta REAL DEFAULT 0.0,
                precio REAL DEFAULT 0.0,
                tipo_producto TEXT DEFAULT 'Producto',
                stock REAL DEFAULT 0.0,
                stock_minimo REAL DEFAULT 0.0,
                stock_bodega REAL DEFAULT 0.0,
                stock_vitrina REAL DEFAULT 0.0,
                stock_minimo_bodega REAL DEFAULT 5.0,
                stock_minimo_vitrina REAL DEFAULT 3.0,
                proveedor_id INTEGER,
                codigo_barras TEXT DEFAULT '',
                imagen_url TEXT DEFAULT '',
                precio_variable INTEGER DEFAULT 0,
                porcentaje_comision REAL DEFAULT 0.0,
                es_material INTEGER DEFAULT 1,
                presentacion_defecto TEXT DEFAULT 'Paquete',
                factor_conversion_defecto REAL DEFAULT 500.0,
                unidad_consumo_defecto TEXT DEFAULT 'Unidad',
                estado TEXT DEFAULT 'Activo',
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            );
        """)
        conn.execute("""
            CREATE TABLE proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT DEFAULT '',
                saldo_acumulado REAL DEFAULT 0.0,
                documento_nit TEXT DEFAULT '',
                email TEXT DEFAULT '',
                direccion TEXT DEFAULT '',
                contacto TEXT DEFAULT '',
                estado TEXT DEFAULT 'Activo',
                total_ventas REAL DEFAULT 0.0,
                total_comisiones REAL DEFAULT 0.0,
                total_pagado REAL DEFAULT 0.0
            );
        """)
        conn.execute("""
            CREATE TABLE usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                clave TEXT NOT NULL,
                rol TEXT NOT NULL DEFAULT 'Administrador',
                nombre TEXT DEFAULT 'Admin',
                apellidos TEXT DEFAULT 'Sistema',
                documento TEXT DEFAULT '00000',
                estado TEXT DEFAULT 'Activo'
            );
        """)
        conn.execute("INSERT INTO usuarios (id, usuario, clave, rol, nombre) VALUES (1, 'admin', 'pass', 'Administrador', 'Admin');")
        conn.execute("INSERT INTO proveedores (id, nombre) VALUES (1, 'omara');")
        conn.execute("""
            INSERT INTO productos (id, codigo, nombre, es_material, unidad_medida, stock_bodega, stock_vitrina, stock, precio_costo, costo)
            VALUES (1, '00001', 'Rexma Carta', 1, 'Unidad', 0.0, 0.0, 0.0, 30.0, 30.0);
        """)
        conn.commit()
        conn.close()

        # Ejecutar migración completa
        asegurar_migraciones_sqlite(f"sqlite:///{self.db_path}")

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_compra_7500_unidades_ajuste_y_traslado(self):
        async def _run():
            url = f"sqlite+aiosqlite:///{self.db_path}"
            engine = create_async_engine(url)
            Session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

            async with Session() as db:
                user = Usuario(id=1, usuario="admin", rol="Administrador", nombre="Admin")

                # 1. Registrar Compra de 15 Paquetes x 500 unidades = 7.500 unidades ingresando a BODEGA
                req_compra = CompraCreate(
                    proveedor_id=1,
                    proveedor_nombre="omara",
                    doc_referencia="FAC-REXMA-01",
                    ubicacion_destino="BODEGA",
                    usuario="admin",
                    observaciones="Compra 15 paquetes Rexma Carta",
                    items=[
                        ItemCompraCreate(
                            producto_id=1,
                            codigo="00001",
                            unidad_compra="Paquete",
                            factor_conversion=500.0,
                            cantidad_comprada=15.0,
                            costo_unidad_compra=15000.0,
                            subtotal=225000.0
                        )
                    ]
                )
                res_cp = await registrar_compra_endpoint(req_compra, db=db, current_user=user)
                self.assertEqual(res_cp["total"], 225000.0)
                self.assertIn("numero_compra", res_cp)

                # 2. Verificar que el producto quedó con 7.500 unidades en BODEGA
                prod = (await db.execute(select(Producto).where(Producto.codigo == "00001"))).scalars().first()
                self.assertIsNotNone(prod)
                self.assertEqual(prod.stock_bodega, 7500.0)
                self.assertEqual(prod.stock, 7500.0)
                self.assertEqual(prod.precio_costo, 30.0)

                # 3. Aplicar Ajuste de Conteo Físico en BODEGA a 1.500 unidades
                req_aj = AjusteInventarioCreate(
                    codigo_o_id="00001",
                    ubicacion="BODEGA",
                    conteo_fisico=1500.0,
                    usuario="admin",
                    motivo="Ajuste a 1.500 unidades reales"
                )
                res_aj = await registrar_ajuste_endpoint(req_aj, db=db, current_user=user)
                self.assertEqual(res_aj["stock_nuevo"], 1500.0)
                self.assertEqual(res_aj["diferencia"], -6000.0)
                self.assertEqual(res_aj["tipo_ajuste"], "AJUSTE_NEGATIVO")

                # Verificar stock actualizado
                await db.refresh(prod)
                self.assertEqual(prod.stock_bodega, 1500.0)
                self.assertEqual(prod.stock, 1500.0)

                # 4. Verificar que en MovimientoInventario se guardaron ambos registros
                res_movs = (await db.execute(select(MovimientoInventario).where(MovimientoInventario.codigo_producto == "00001"))).scalars().all()
                self.assertEqual(len(res_movs), 2)
                self.assertEqual(res_movs[0].tipo, "ENTRADA_COMPRA")
                self.assertEqual(res_movs[0].tipo_movimiento, "ENTRADA_COMPRA")
                self.assertEqual(res_movs[0].cantidad, 7500.0)

                self.assertEqual(res_movs[1].tipo, "AJUSTE_NEGATIVO")
                self.assertEqual(res_movs[1].tipo_movimiento, "AJUSTE_NEGATIVO")
                self.assertEqual(res_movs[1].cantidad, 6000.0)

            await engine.dispose()

        asyncio.run(_run())

        # 5. Probar Traslado de Bodega a Trabajador usando SQLite directo
        import interface.materiales_manager as mm
        orig_conectar = mm.conectar_db
        mm.conectar_db = lambda: sqlite3.connect(self.db_path)

        try:
            res_traslado = trasladar_bodega_a_operario(
                producto_id=1,
                usuario_destino="admin",
                cantidad_unidades=100.0,
                usuario_responsable="admin",
                observaciones="Entrega para produccion"
            )
            self.assertTrue(res_traslado["ok"])
            self.assertEqual(res_traslado["saldo_bodega_restante"], 1400.0)
            self.assertEqual(res_traslado["saldo_operario_nuevo"], 100.0)

            # Verificar en base de datos
            c = sqlite3.connect(self.db_path)
            cur = c.cursor()
            cur.execute("SELECT stock_bodega, stock FROM productos WHERE id = 1")
            sb, st = cur.fetchone()
            self.assertEqual(sb, 1400.0)
            self.assertEqual(st, 1400.0)

            cur.execute("SELECT stock_disponible, total_recibido FROM inventario_operarios WHERE usuario_nombre = 'admin' AND producto_id = 1")
            s_op, tot_rec = cur.fetchone()
            self.assertEqual(s_op, 100.0)
            self.assertEqual(tot_rec, 100.0)
            c.close()
        finally:
            mm.conectar_db = orig_conectar


if __name__ == "__main__":
    unittest.main()
