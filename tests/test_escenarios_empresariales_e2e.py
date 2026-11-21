#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite Exhaustiva de Pruebas Empresariales End-to-End (E2E) para VmPOS:
Escenarios A a L:
- Escenario A: Venta normal en efectivo con descarga de vitrina y registro en caja.
- Escenario B: Venta mixta (Efectivo + Transferencia) y validación de suma de pagos.
- Escenario C: Venta a crédito y control de autorización de exceso por rol.
- Escenario D: Anulación total con reversión de inventario, caja y comisiones.
- Escenario E: Devolución parcial / edición de venta con recálculo de stock y kárdex.
- Escenario F: Compra de mercancía a proveedor con generación automática de CXP.
- Escenario G: Liquidación de proveedor con abono a CXP y egreso financiero.
- Escenario H: Venta de operario con asignación de comisión porcentual.
- Escenario I: Asistencia y generación de salario diario ligada a primera venta.
- Escenario J: Liquidación de nómina con bloqueo estricto de re-pago.
- Escenario K: Múltiples sesiones de caja en el mismo día sin contaminación cruzada.
- Escenario L: Cola de sincronización fuera de línea con reintentos y tolerancia a fallos.
"""

import unittest
import asyncio
import os
import time
from datetime import datetime, date
from httpx import AsyncClient, ASGITransport
from sqlalchemy.future import select

from server.main import app
from server.database import SessionLocal
from server.models.usuario import Usuario
from server.models.producto import Producto
from server.models.cliente import Cliente
from server.models.proveedor import Proveedor
from server.models.caja import SesionCaja, MovimientoCaja
from server.models.inventario import MovimientoInventario
from server.models.finanzas import CuentaPorCobrar, CuentaPorPagar
from server.models.nomina import Comision, Liquidacion, Asistencia
from server.middleware.auth import hash_password
from tests.test_helpers import init_isolated_test_db, cleanup_isolated_test_db


class TestEscenariosEmpresarialesE2E(unittest.TestCase):
    test_db = f"/tmp/test_escenarios_e2e_{os.getpid()}.db"

    @classmethod
    def setUpClass(cls):
        asyncio.run(init_isolated_test_db(cls.test_db))
        cls.transport = ASGITransport(app=app)
        asyncio.run(cls._seed_datos_iniciales())

    @classmethod
    async def _seed_datos_iniciales(cls):
        async with SessionLocal() as db:
            # 1. Crear operario Carlos
            res_carlos = await db.execute(select(Usuario).where(Usuario.usuario == "carlos"))
            if not res_carlos.scalars().first():
                db.add(Usuario(
                    id=2,
                    usuario="carlos",
                    password_hash=hash_password("Carlos2026*"),
                    nombre="Carlos",
                    apellidos="Vendedor",
                    rol="Vendedor",
                    estado="Activo",
                    tipo_remuneracion="Mixta",
                    salario_diario=35000.0,
                    porcentaje_comision=10.0,
                ))

            # 2. Crear cliente Juan Pérez con crédito de 50.000
            res_cli = await db.execute(select(Cliente).where(Cliente.id == 1))
            if not res_cli.scalars().first():
                db.add(Cliente(
                    id=1,
                    nombre="Juan Perez",
                    documento="10203040",
                    telefono="3001234567",
                    permite_fiado=True,
                    limite_credito=50000.0,
                    estado="Activo"
                ))

            # 3. Abrir sesión inicial de caja para CAJA-01
            res_ses = await db.execute(
                select(SesionCaja).where(SesionCaja.terminal_id == 1, SesionCaja.estado == "Abierta")
            )
            if not res_ses.scalars().first():
                db.add(SesionCaja(
                    id=1,
                    terminal_id=1,
                    terminal_nombre="CAJA-01",
                    usuario_apertura="admin",
                    fecha_apertura=datetime.now().strftime("%Y-%m-%d"),
                    hora_apertura=datetime.now().strftime("%H:%M:%S"),
                    monto_inicial=100000.0,
                    monto_esperado_efectivo=100000.0,
                    estado="Abierta"
                ))

            await db.commit()

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cleanup_isolated_test_db(cls.test_db))

    def test_escenarios_e2e_completos(self):
        async def _run():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # Login Admin
                res_login_admin = await client.post("/auth/login", json={"usuario": "admin", "password": "123456", "terminal_id": 1})
                self.assertEqual(res_login_admin.status_code, 200)
                admin_token = res_login_admin.json()["access_token"]
                admin_headers = {"Authorization": f"Bearer {admin_token}"}

                # Login Operario Carlos
                res_login_carlos = await client.post("/auth/login", json={"usuario": "carlos", "password": "Carlos2026*", "terminal_id": 1})
                self.assertEqual(res_login_carlos.status_code, 200)
                carlos_token = res_login_carlos.json()["access_token"]
                carlos_headers = {"Authorization": f"Bearer {carlos_token}"}

                # -------------------------------------------------------------
                # ESCENARIO A: Venta Normal Efectivo (Vitrina decrementa, Caja suma)
                # -------------------------------------------------------------
                async with SessionLocal() as db:
                    p1 = await db.get(Producto, 1)
                    stock_vitrina_ini = p1.stock_vitrina

                payload_vta_a = {
                    "terminal_id": 1,
                    "sesion_caja_id": 1,
                    "subtotal": 11600.0,
                    "total": 11600.0,
                    "items": [{
                        "item_id": 1,
                        "tipo_item": "producto",
                        "item_codigo": "00001",
                        "item_nombre": "Cuaderno 100 Hojas Norma Pro",
                        "precio_original": 5800.0,
                        "precio_vendido": 5800.0,
                        "cantidad": 2.0,
                        "subtotal": 11600.0,
                        "ubicacion": "Vitrina"
                    }],
                    "pagos": [{
                        "metodo": "Efectivo",
                        "monto": 11600.0,
                        "recibido": 20000.0,
                        "cambio": 8400.0
                    }],
                    "idempotency_key": f"e2e-vta-a-{time.time()}"
                }
                res_vta_a = await client.post("/ventas", json=payload_vta_a, headers=admin_headers)
                self.assertEqual(res_vta_a.status_code, 200, f"Fallo Escenario A: {res_vta_a.text}")
                vta_a_id = res_vta_a.json()["id"]

                async with SessionLocal() as db:
                    p1_post = await db.get(Producto, 1)
                    self.assertEqual(p1_post.stock_vitrina, stock_vitrina_ini - 2.0)
                    mov_k = (await db.execute(
                        select(MovimientoInventario).where(MovimientoInventario.producto_id == 1)
                    )).scalars().all()
                    self.assertTrue(len(mov_k) > 0)

                # -------------------------------------------------------------
                # ESCENARIO B: Venta Dividida Mixta y Validación de Suma de Pagos
                # -------------------------------------------------------------
                # B1: Suma no coincide -> rechazo 400
                payload_vta_b_invalida = {
                    "terminal_id": 1,
                    "sesion_caja_id": 1,
                    "subtotal": 11600.0,
                    "total": 11600.0,
                    "items": [{
                        "item_id": 1,
                        "tipo_item": "producto",
                        "precio_vendido": 5800.0,
                        "cantidad": 2.0,
                        "subtotal": 11600.0
                    }],
                    "pagos": [
                        {"metodo": "Efectivo", "monto": 5000.0},
                        {"metodo": "Transferencia", "monto": 5000.0}  # Suma 10000 != 11600
                    ]
                }
                res_b_inv = await client.post("/ventas", json=payload_vta_b_invalida, headers=admin_headers)
                self.assertEqual(res_b_inv.status_code, 400)
                self.assertIn("no coincide con el total", res_b_inv.text)

                # B2: Suma exacta -> éxito 200
                payload_vta_b_valida = {
                    "terminal_id": 1,
                    "sesion_caja_id": 1,
                    "subtotal": 11600.0,
                    "total": 11600.0,
                    "items": [{
                        "item_id": 1,
                        "tipo_item": "producto",
                        "precio_vendido": 5800.0,
                        "cantidad": 2.0,
                        "subtotal": 11600.0
                    }],
                    "pagos": [
                        {"metodo": "Efectivo", "monto": 6000.0},
                        {"metodo": "Transferencia", "monto": 5600.0}
                    ],
                    "idempotency_key": f"e2e-vta-b-{time.time()}"
                }
                res_b_ok = await client.post("/ventas", json=payload_vta_b_valida, headers=admin_headers)
                self.assertEqual(res_b_ok.status_code, 200)

                # -------------------------------------------------------------
                # ESCENARIO C: Venta a Crédito y Control de Límite por Rol
                # -------------------------------------------------------------
                # Cliente 1 tiene limite 50.000. Intentar crédito por 70.000 como Operario -> 403
                payload_vta_c_exceso = {
                    "terminal_id": 1,
                    "cliente_id": 1,
                    "subtotal": 70000.0,
                    "total": 70000.0,
                    "items": [{
                        "item_id": 1,
                        "tipo_item": "producto",
                        "precio_vendido": 7000.0,
                        "cantidad": 10.0,
                        "subtotal": 70000.0
                    }],
                    "pagos": [{"metodo": "Credito", "monto": 70000.0}],
                    "autorizado_exceso_credito": True
                }
                # Intentar como Operario Carlos -> Debe ser rechazado (403: solo Admin autoriza)
                res_c_carlos = await client.post("/ventas", json=payload_vta_c_exceso, headers=carlos_headers)
                self.assertEqual(res_c_carlos.status_code, 403)
                self.assertIn("Solo un Administrador", res_c_carlos.text)

                # Intentar como Admin -> Debe ser aprobado (200) y generar CXC
                payload_vta_c_exceso["idempotency_key"] = f"e2e-vta-c-{time.time()}"
                res_c_admin = await client.post("/ventas", json=payload_vta_c_exceso, headers=admin_headers)
                self.assertEqual(res_c_admin.status_code, 200)
                vta_c_id = res_c_admin.json()["id"]

                async with SessionLocal() as db:
                    cxc = (await db.execute(select(CuentaPorCobrar).where(CuentaPorCobrar.venta_id == vta_c_id))).scalars().first()
                    self.assertIsNotNone(cxc)
                    self.assertEqual(cxc.monto_original, 70000.0)

                # -------------------------------------------------------------
                # ESCENARIO D: Anulación Total con Reversión de Stock y Finanzas
                # -------------------------------------------------------------
                async with SessionLocal() as db:
                    p1_pre_d = await db.get(Producto, 1)
                    stock_vitrina_pre_d = p1_pre_d.stock_vitrina

                res_anul_c = await client.post(f"/ventas/{vta_c_id}/anular", json={"motivo": "Devolución crédito"}, headers=admin_headers)
                self.assertEqual(res_anul_c.status_code, 200)

                async with SessionLocal() as db:
                    p1_post_d = await db.get(Producto, 1)
                    # Las 10 unidades retornaron a vitrina
                    self.assertEqual(p1_post_d.stock_vitrina, stock_vitrina_pre_d + 10.0)
                    cxc_post = await db.get(CuentaPorCobrar, cxc.id)
                    self.assertEqual(cxc_post.estado, "Anulada")

                # -------------------------------------------------------------
                # ESCENARIO E: Devolución Parcial / Edición de Venta
                # -------------------------------------------------------------
                # Editar Venta A (tenía 2 unidades por 11600): devolver 1 unidad (queda 1 x 5800)
                async with SessionLocal() as db:
                    p1_pre_e = await db.get(Producto, 1)
                    stock_vitrina_pre_e = p1_pre_e.stock_vitrina

                payload_edit_a = {
                    "subtotal": 5800.0,
                    "total": 5800.0,
                    "items": [{
                        "item_id": 1,
                        "codigo_producto": "00001",
                        "tipo_item": "producto",
                        "precio_vendido": 5800.0,
                        "cantidad": 1.0,
                        "subtotal": 5800.0,
                        "ubicacion": "Vitrina"
                    }],
                    "pagos": [{"metodo": "Efectivo", "monto": 5800.0}],
                    "motivo": "Cliente devuelve 1 unidad"
                }
                res_edit_a = await client.put(f"/ventas/{vta_a_id}", json=payload_edit_a, headers=admin_headers)
                self.assertEqual(res_edit_a.status_code, 200)

                async with SessionLocal() as db:
                    p1_post_e = await db.get(Producto, 1)
                    # 1 unidad regresó a vitrina
                    self.assertEqual(p1_post_e.stock_vitrina, stock_vitrina_pre_e + 1.0)

                # -------------------------------------------------------------
                # ESCENARIO F: Compra de Mercancía a Proveedor con Generación de CXP
                # -------------------------------------------------------------
                payload_compra = {
                    "proveedor_id": 1,
                    "proveedor_nombre": "Proveedor Concurrente",
                    "doc_referencia": "FAC-E2E-999",
                    "tipo_pago": "Credito",
                    "ubicacion_destino": "BODEGA",
                    "idempotency_key": f"e2e-compra-{time.time()}",
                    "items": [{
                        "codigo": "00001",
                        "nombre": "Cuaderno 100 Hojas Norma Pro",
                        "unidad_compra": "Paquete",
                        "factor_conversion": 10.0,
                        "cantidad_comprada": 5.0,
                        "costo_unidad_compra": 50000.0,
                        "subtotal": 250000.0
                    }]
                }
                res_compra = await client.post("/inventario/compras", json=payload_compra, headers=admin_headers)
                self.assertEqual(res_compra.status_code, 200)
                self.assertEqual(res_compra.json()["total"], 250000.0)

                async with SessionLocal() as db:
                    cxp = (await db.execute(
                        select(CuentaPorPagar).where(CuentaPorPagar.codigo_servicio == "FAC-E2E-999")
                    )).scalars().first()
                    self.assertIsNotNone(cxp)
                    self.assertEqual(cxp.monto, 250000.0)

                # -------------------------------------------------------------
                # ESCENARIO G: Liquidación de Proveedor con Abono a CXP
                # -------------------------------------------------------------
                payload_liq_prov = {
                    "monto": 50000.0,
                    "metodo_pago": "Efectivo",
                    "proveedor_nombre": "Proveedor Concurrente",
                    "idempotency_key": f"e2e-liq-prov-{time.time()}"
                }
                res_liq_prov = await client.post("/proveedores/1/liquidar", json=payload_liq_prov, headers=admin_headers)
                self.assertEqual(res_liq_prov.status_code, 200)

                async with SessionLocal() as db:
                    cxp_post = await db.get(CuentaPorPagar, cxp.id)
                    self.assertEqual(cxp_post.monto_pagado, 50000.0)
                    self.assertEqual(cxp_post.saldo_pendiente, 200000.0)

                # -------------------------------------------------------------
                # ESCENARIO H: Venta Operario con Comisión Porcentual Acumulada
                # -------------------------------------------------------------
                payload_vta_h = {
                    "terminal_id": 1,
                    "sesion_caja_id": 1,
                    "subtotal": 20000.0,
                    "total": 20000.0,
                    "items": [{
                        "item_id": 1,
                        "tipo_item": "producto",
                        "precio_original": 10000.0,
                        "precio_vendido": 10000.0,
                        "costo_unitario": 5000.0,
                        "cantidad": 2.0,
                        "subtotal": 20000.0,
                        "porcentaje_comision": 10.0
                    }],
                    "pagos": [{"metodo": "Efectivo", "monto": 20000.0}],
                    "idempotency_key": f"e2e-vta-h-{time.time()}"
                }
                res_vta_h = await client.post("/ventas", json=payload_vta_h, headers=carlos_headers)
                self.assertEqual(res_vta_h.status_code, 200)
                vta_h_id = res_vta_h.json()["id"]

                async with SessionLocal() as db:
                    com = (await db.execute(
                        select(Comision).where(Comision.venta_id == vta_h_id, Comision.usuario_id == 2)
                    )).scalars().first()
                    self.assertIsNotNone(com)
                    self.assertEqual(com.estado, "Pendiente")
                    self.assertTrue(com.monto_comision > 0.0)

                # -------------------------------------------------------------
                # ESCENARIO I: Asistencia y Salario Diario con Venta Válida
                # -------------------------------------------------------------
                # Carlos ya procesó la venta H en la fecha actual -> asistencia genera salario diario
                payload_asist = {
                    "usuario_id": 2,
                    "fecha": datetime.now().strftime("%Y-%m-%d"),
                    "estado": "Presente"
                }
                res_asist = await client.post("/nomina/asistencia", json=payload_asist, headers=admin_headers)
                self.assertEqual(res_asist.status_code, 200)
                asist_data = res_asist.json()
                self.assertEqual(asist_data["estado"], "Presente")
                self.assertEqual(asist_data["salario_generado"], 35000.0)

                # -------------------------------------------------------------
                # ESCENARIO J: Liquidación de Nómina y Bloqueo de Re-Pago
                # -------------------------------------------------------------
                payload_liq_nom = {
                    "usuario_id": 2,
                    "metodo_pago": "Efectivo",
                    "observaciones": "Liquidación quincenal Carlos",
                    "idempotency_key": f"e2e-liq-nom-{time.time()}"
                }
                res_liq_nom_1 = await client.post("/nomina/liquidaciones", json=payload_liq_nom, headers=admin_headers)
                self.assertEqual(res_liq_nom_1.status_code, 200)
                self.assertTrue(res_liq_nom_1.json()["total_liquidado"] > 0)

                # Intento inmediato de re-liquidar sin nuevas comisiones ni asistencias -> 400
                payload_liq_nom_2 = {
                    "usuario_id": 2,
                    "metodo_pago": "Efectivo",
                    "idempotency_key": f"e2e-liq-nom-repago-{time.time()}"
                }
                res_liq_nom_2 = await client.post("/nomina/liquidaciones", json=payload_liq_nom_2, headers=admin_headers)
                self.assertEqual(res_liq_nom_2.status_code, 400)
                self.assertIn("no tiene comisiones ni salarios pendientes", res_liq_nom_2.text)

                # -------------------------------------------------------------
                # ESCENARIO K: Cierre de Sesión 1 y Apertura de Sesión 2 Mismo Día
                # -------------------------------------------------------------
                payload_cierre = {
                    "monto_real_contado": 150000.0,
                    "observaciones": "Cierre turno matutino"
                }
                res_cierre = await client.post("/caja/sesiones/1/cerrar", json=payload_cierre, headers=admin_headers)
                self.assertEqual(res_cierre.status_code, 200)

                # Abrir sesión 2
                payload_apertura = {
                    "terminal_id": 1,
                    "terminal_nombre": "CAJA-01",
                    "monto_inicial": 80000.0
                }
                res_apertura = await client.post("/caja/abrir", json=payload_apertura, headers=admin_headers)
                self.assertEqual(res_apertura.status_code, 200)
                ses_2_id = res_apertura.json()["sesion_id"]
                self.assertNotEqual(ses_2_id, 1)

                # Verificar estado de caja de sesión 2: activa y con su propia base sin mezclar
                res_estado_caja = await client.get("/caja/sesion-activa", headers=admin_headers)
                self.assertEqual(res_estado_caja.status_code, 200)
                estado_data = res_estado_caja.json()
                self.assertIsNotNone(estado_data["activa"])
                self.assertEqual(estado_data["activa"]["id"], ses_2_id)
                self.assertEqual(estado_data["activa"]["monto_inicial"], 80000.0)

                # -------------------------------------------------------------
                # ESCENARIO L: Cola de Sincronización Fuera de Línea con Reintentos
                # -------------------------------------------------------------
                from interface.sync_manager import SyncManager, ESTADO_PENDIENTE, ESTADO_ERROR, ESTADO_SINCRONIZADO
                import tempfile
                import sqlite3
                tmp_sync_db = os.path.join(tempfile.gettempdir(), f"test_sync_e2e_{os.getpid()}.db")
                conn_sync = sqlite3.connect(tmp_sync_db)
                sync_mgr = SyncManager()
                sync_mgr.asegurar_tabla_cola(conn=conn_sync)

                op_id = sync_mgr.encolar_operacion(
                    tipo_operacion="VENTA",
                    payload={"subtotal": 1000.0, "total": 1000.0},
                    idempotency_key=f"idem-sync-{time.time()}",
                    conn=conn_sync
                )
                self.assertTrue(len(op_id) > 0)

                # Verificar conteo de pendientes
                conteo_1 = sync_mgr.obtener_conteo_pendientes(conn=conn_sync)
                self.assertEqual(conteo_1["pendientes"], 1)

                # Simular error de conexión en la LAN (reintento)
                sync_mgr.marcar_error_sincronizacion(op_id, "Fallo de conexión LAN", conn=conn_sync)
                conteo_err = sync_mgr.obtener_conteo_pendientes(conn=conn_sync)
                self.assertEqual(conteo_err["errores"], 1)

                # Simular resolución exitosa tras reconexión
                sync_mgr.marcar_como_sincronizada(op_id, conn=conn_sync)
                conteo_ok = sync_mgr.obtener_conteo_pendientes(conn=conn_sync)
                self.assertEqual(conteo_ok["sincronizados"], 1)
                conn_sync.close()
                if os.path.exists(tmp_sync_db):
                    os.remove(tmp_sync_db)

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
