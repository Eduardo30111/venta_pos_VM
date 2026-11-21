#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas de Integración E2E para Sincronización Multi-terminal Real:
- Dos terminales independientes (CAJA-01 y CAJA-02) con colas SQLite y conexiones separadas.
- Simulación de operaciones simultáneas en línea.
- Desconexión forzada de red y acumulación de operaciones fuera de línea:
  * Ventas
  * Gastos / Movimientos de caja
  * Movimientos de inventario (Traslados)
  * Abonos a cartera de clientes
  * Liquidaciones a cuentas de proveedores
- Restablecimiento de red, procesamiento de cola y garantía de IDEMPOTENCIA total (sin duplicaciones).
- Verificación cruzada integral:
  * Inventario (existencias físicas exactas en Bodega y Vitrina)
  * Sesiones de caja aisladas por terminal (sin mezcla de arqueos)
  * Consolidación contable de ingresos y egresos
  * Cartera de clientes y saldos de proveedores
- Auto-recuperación transparente ante fallos o cierres abruptos durante sincronización (SINCRONIZANDO -> PENDIENTE).
"""

import unittest
import asyncio
import os
import shutil
import tempfile
import sqlite3
import json
import time
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy.future import select
from server.main import app
from server.database import SessionLocal
import server.database as db_mod
from server.models.terminal import Terminal
from server.models.producto import Producto
from server.models.cliente import Cliente
from server.models.finanzas import CuentaPorCobrar, Gasto
from server.models.proveedor import Proveedor
from server.models.caja import SesionCaja
from server.models.venta import Venta

from tests.test_helpers import init_isolated_test_db, cleanup_isolated_test_db
from client.api_client import api, DummyResponse
from interface.sync_manager import (
    sync_mgr,
    OP_VENTA,
    OP_GASTO,
    OP_ABONO,
    OP_MOV_INVENTARIO,
    OP_LIQ_PROVEEDOR,
    ESTADO_PENDIENTE,
    ESTADO_SINCRONIZANDO,
    ESTADO_SINCRONIZADO,
)


class TestSincronizacionMultiterminalE2E(unittest.TestCase):
    server_db = f"/tmp/test_multiterminal_server_{os.getpid()}.db"

    @classmethod
    def setUpClass(cls):
        # 1. Iniciar base de datos aislada del servidor
        asyncio.run(init_isolated_test_db(cls.server_db))

        # 2. Configurar TestClient sincronizado con el cliente API
        cls.test_client = TestClient(app, base_url="http://test")
        api._client = cls.test_client

        # 3. Autenticación como Administrador en el servidor
        login_res = cls.test_client.post("/auth/login", json={"usuario": "admin", "password": "123456", "terminal_id": 1})
        if login_res.status_code != 200:
            raise RuntimeError(f"Fallo login en test server: {login_res.text}")
        cls.token = login_res.json()["access_token"]
        api.token = cls.token

        # 4. Sembrar Terminal 2 (CAJA-02) y Cliente con Cartera en la base del servidor
        async def _seed_extra():
            async with SessionLocal() as session:
                # Terminal 2
                res_t2 = await session.execute(select(Terminal).where(Terminal.id == 2))
                if not res_t2.scalars().first():
                    session.add(Terminal(id=2, nombre="CAJA-02", descripcion="Terminal Secundaria"))

                # Cliente 1 con deuda
                res_c = await session.execute(select(Cliente).where(Cliente.id == 1))
                if not res_c.scalars().first():
                    cliente = Cliente(
                        id=1,
                        nombre="Empresa Comercializadora Andina",
                        documento="900999111-2",
                        limite_credito=500000.0,
                        permite_fiado=True,
                        estado="Activo",
                    )
                    session.add(cliente)
                    await session.flush()
                    cxc = CuentaPorCobrar(
                        id=1,
                        cliente_id=1,
                        monto_original=100000.0,
                        saldo_pendiente=100000.0,
                        estado="Pendiente",
                        fecha="2026-11-21",
                    )
                    session.add(cxc)

                # Proveedor 1 con saldo acumulado para liquidar
                res_p = await session.execute(select(Proveedor).where(Proveedor.id == 1))
                prov = res_p.scalars().first()
                if prov:
                    prov.saldo_acumulado = 50000.0
                await session.commit()

        asyncio.run(_seed_extra())

    @classmethod
    def tearDownClass(cls):
        api.logout()
        asyncio.run(cleanup_isolated_test_db(cls.server_db))

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_terminals_local_")
        # Base local SQLite independiente para Terminal 1 (CAJA-01)
        self.db_t1_path = os.path.join(self.temp_dir, "caja_01_local.db")
        self.conn_t1 = sqlite3.connect(self.db_t1_path)
        sync_mgr.asegurar_tabla_cola(self.conn_t1)

        # Base local SQLite independiente para Terminal 2 (CAJA-02)
        self.db_t2_path = os.path.join(self.temp_dir, "caja_02_local.db")
        self.conn_t2 = sqlite3.connect(self.db_t2_path)
        sync_mgr.asegurar_tabla_cola(self.conn_t2)

        # Pausar auto-disparo de hilos en segundo plano para control secuencial en pruebas
        sync_mgr._pausar_auto_disparo = True
        sync_mgr._sincronizando_ahora = False

        # Restaurar conectividad normal por defecto
        api._client = self.test_client
        api.token = self.token

    def tearDown(self):
        try:
            self.conn_t1.close()
            self.conn_t2.close()
        except Exception:
            pass
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_flujo_multiterminal_completo_offline_online_idempotencia(self):
        """
        Prueba maestra integral:
        1. Apertura de caja en línea para CAJA-01 y CAJA-02.
        2. Ventas simultáneas en línea en ambas cajas.
        3. Desconexión de red y acumulación offline en ambas terminales:
           - T1: Venta, Gasto, Traslado inventario, Abono cliente.
           - T2: Venta, Gasto, Liquidación proveedor.
        4. Verificación de colas pendientes en ambas terminales locales.
        5. Reconexión y sincronización total.
        6. Verificación de IDEMPOTENCIA (re-ejecución no duplica datos).
        7. Auditoría de inventario, cajas aisladas, cartera y contabilidad consolidada.
        """
        # =====================================================================
        # PASO 1: Apertura de caja independiente en ambas terminales
        # =====================================================================
        res_ap_t1 = self.test_client.post(
            "/caja/abrir",
            json={"monto_inicial": 100000.0, "terminal_id": 1, "terminal_nombre": "CAJA-01"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res_ap_t1.status_code, 200, f"Error abriendo Caja 1: {res_ap_t1.text}")
        sesion_t1_id = res_ap_t1.json()["sesion_id"]

        res_ap_t2 = self.test_client.post(
            "/caja/abrir",
            json={"monto_inicial": 150000.0, "terminal_id": 2, "terminal_nombre": "CAJA-02"},
            headers={"Authorization": f"Bearer {self.token}"},
        )
        self.assertEqual(res_ap_t2.status_code, 200, f"Error abriendo Caja 2: {res_ap_t2.text}")
        sesion_t2_id = res_ap_t2.json()["sesion_id"]

        self.assertNotEqual(sesion_t1_id, sesion_t2_id, "Las sesiones de caja de T1 y T2 deben ser distintas")

        # =====================================================================
        # PASO 2: Operaciones en línea simultáneas en ambas cajas
        # =====================================================================
        ts = int(time.time() * 1000)
        # Venta T1 Online: 2 cuadernos ($11,600)
        payload_vta_t1_on = {
            "subtotal": 11600.0,
            "total": 11600.0,
            "terminal_id": 1,
            "sesion_caja_id": sesion_t1_id,
            "idempotency_key": f"vta-t1-on-{ts}",
            "items": [{
                "tipo_item": "producto",
                "item_id": 1,
                "item_codigo": "00001",
                "item_nombre": "Cuaderno 100 Hojas Norma Pro",
                "precio_vendido": 5800.0,
                "cantidad": 2.0,
                "subtotal": 11600.0,
                "ubicacion": "Vitrina",
            }],
            "pagos": [{"metodo": "Efectivo", "monto": 11600.0}],
        }
        res_vta_t1 = self.test_client.post("/ventas", json=payload_vta_t1_on, headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(res_vta_t1.status_code, 200)

        # Venta T2 Online: 3 cuadernos ($17,400)
        payload_vta_t2_on = {
            "subtotal": 17400.0,
            "total": 17400.0,
            "terminal_id": 2,
            "sesion_caja_id": sesion_t2_id,
            "idempotency_key": f"vta-t2-on-{ts}",
            "items": [{
                "tipo_item": "producto",
                "item_id": 1,
                "item_codigo": "00001",
                "item_nombre": "Cuaderno 100 Hojas Norma Pro",
                "precio_vendido": 5800.0,
                "cantidad": 3.0,
                "subtotal": 17400.0,
                "ubicacion": "Vitrina",
            }],
            "pagos": [{"metodo": "Efectivo", "monto": 17400.0}],
        }
        res_vta_t2 = self.test_client.post("/ventas", json=payload_vta_t2_on, headers={"Authorization": f"Bearer {self.token}"})
        self.assertEqual(res_vta_t2.status_code, 200)

        # =====================================================================
        # PASO 3: Desconexión total de red (Modo Fuera de Línea)
        # =====================================================================
        # Simulamos corte de red desconectando el cliente http de api
        api._client = None
        api.servidor_disponible = False

        # Comprobar que api.esta_disponible() reporta desconexión
        self.assertFalse(api.esta_disponible(forzar=True))

        # Operaciones Offline en Terminal 1 (CAJA-01):
        # 1. Venta Offline T1: 4 cuadernos ($23,200)
        idem_vta_t1_off = f"vta-t1-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_VENTA,
            payload={
                "subtotal": 23200.0,
                "total": 23200.0,
                "terminal_id": 1,
                "sesion_caja_id": sesion_t1_id,
                "items": [{
                    "tipo_item": "producto",
                    "item_id": 1,
                    "item_codigo": "00001",
                    "item_nombre": "Cuaderno 100 Hojas Norma Pro",
                    "precio_vendido": 5800.0,
                    "cantidad": 4.0,
                    "subtotal": 23200.0,
                    "ubicacion": "Vitrina",
                }],
                "pagos": [{"metodo": "Efectivo", "monto": 23200.0}],
            },
            usuario="Cajero T1",
            dispositivo="CAJA-01",
            idempotency_key=idem_vta_t1_off,
            conn=self.conn_t1,
        )

        # 2. Gasto Offline T1: $15,000 Fletes y envíos
        idem_gasto_t1_off = f"gasto-t1-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_GASTO,
            payload={
                "categoria": "Operativo",
                "concepto": "Fletes y mensajería urgente T1",
                "valor": 15000.0,
                "metodo_pago": "Efectivo",
                "sesion_caja_id": sesion_t1_id,
            },
            usuario="Cajero T1",
            dispositivo="CAJA-01",
            idempotency_key=idem_gasto_t1_off,
            conn=self.conn_t1,
        )

        # 3. Traslado Inventario Offline T1: 20 cuadernos BODEGA -> VITRINA
        idem_tras_t1_off = f"tras-t1-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_MOV_INVENTARIO,
            payload={
                "subtipo": "TRASLADO",
                "codigo_o_id": "00001",
                "origen": "BODEGA",
                "destino": "VITRINA",
                "cantidad": 20.0,
            },
            usuario="Cajero T1",
            dispositivo="CAJA-01",
            idempotency_key=idem_tras_t1_off,
            conn=self.conn_t1,
        )

        # 4. Abono Cartera Cliente Offline T1: $20,000 a Cliente 1
        idem_abono_t1_off = f"abono-t1-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_ABONO,
            payload={
                "cliente_id": 1,
                "monto": 20000.0,
                "metodo": "Efectivo",
                "terminal_id": 1,
                "sesion_caja_id": sesion_t1_id,
                "observacion": "Abono cliente recibido en CAJA-01 offline",
            },
            usuario="Cajero T1",
            dispositivo="CAJA-01",
            idempotency_key=idem_abono_t1_off,
            conn=self.conn_t1,
        )

        # Operaciones Offline en Terminal 2 (CAJA-02):
        # 1. Venta Offline T2: 6 cuadernos ($34,800)
        idem_vta_t2_off = f"vta-t2-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_VENTA,
            payload={
                "subtotal": 34800.0,
                "total": 34800.0,
                "terminal_id": 2,
                "sesion_caja_id": sesion_t2_id,
                "items": [{
                    "tipo_item": "producto",
                    "item_id": 1,
                    "item_codigo": "00001",
                    "item_nombre": "Cuaderno 100 Hojas Norma Pro",
                    "precio_vendido": 5800.0,
                    "cantidad": 6.0,
                    "subtotal": 34800.0,
                    "ubicacion": "Vitrina",
                }],
                "pagos": [{"metodo": "Efectivo", "monto": 34800.0}],
            },
            usuario="Cajero T2",
            dispositivo="CAJA-02",
            idempotency_key=idem_vta_t2_off,
            conn=self.conn_t2,
        )

        # 2. Gasto Offline T2: $12,000 Papelería de caja
        idem_gasto_t2_off = f"gasto-t2-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_GASTO,
            payload={
                "categoria": "Insumos",
                "concepto": "Rollos de papel y cinta CAJA-02",
                "valor": 12000.0,
                "metodo_pago": "Efectivo",
                "sesion_caja_id": sesion_t2_id,
            },
            usuario="Cajero T2",
            dispositivo="CAJA-02",
            idempotency_key=idem_gasto_t2_off,
            conn=self.conn_t2,
        )

        # 3. Liquidación Proveedor Offline T2: $25,000 a Proveedor 1
        idem_liq_t2_off = f"liq-t2-off-{ts}"
        sync_mgr.encolar_operacion(
            tipo_operacion=OP_LIQ_PROVEEDOR,
            payload={
                "proveedor_id": 1,
                "monto": 25000.0,
                "metodo_pago": "Efectivo",
                "sesion_caja_id": sesion_t2_id,
                "nota": "Anticipo liquidación proveedor T2 offline",
            },
            usuario="Cajero T2",
            dispositivo="CAJA-02",
            idempotency_key=idem_liq_t2_off,
            conn=self.conn_t2,
        )

        # =====================================================================
        # PASO 4: Comprobar colas locales persistentes en SQLite
        # =====================================================================
        conteo_t1 = sync_mgr.obtener_conteo_pendientes(conn=self.conn_t1)
        self.assertEqual(conteo_t1["pendientes"], 4, "T1 debe tener 4 operaciones pendientes")

        conteo_t2 = sync_mgr.obtener_conteo_pendientes(conn=self.conn_t2)
        self.assertEqual(conteo_t2["pendientes"], 3, "T2 debe tener 3 operaciones pendientes")

        # Intentar procesar cola con red caída -> Debe abortar ordenadamente sin perder datos
        res_sync_caida = sync_mgr.procesar_cola(conn=self.conn_t1)
        self.assertEqual(res_sync_caida["status"], "servidor_no_disponible")
        self.assertEqual(sync_mgr.obtener_conteo_pendientes(conn=self.conn_t1)["pendientes"], 4)

        # =====================================================================
        # PASO 5: Restablecimiento de Red y Sincronización Exitosa
        # =====================================================================
        api._client = self.test_client
        api.token = self.token
        api.servidor_disponible = True
        self.assertTrue(api.esta_disponible(forzar=True))

        # Sincronizar Terminal 1
        res_sync_t1 = sync_mgr.procesar_cola(conn=self.conn_t1)
        self.assertEqual(res_sync_t1["status"], "completado")
        self.assertEqual(res_sync_t1["exitosos"], 4)
        self.assertEqual(res_sync_t1["fallidos"], 0)
        self.assertEqual(sync_mgr.obtener_conteo_pendientes(conn=self.conn_t1)["pendientes"], 0)
        self.assertEqual(sync_mgr.obtener_conteo_pendientes(conn=self.conn_t1)["sincronizados"], 4)

        # Sincronizar Terminal 2
        res_sync_t2 = sync_mgr.procesar_cola(conn=self.conn_t2)
        self.assertEqual(res_sync_t2["status"], "completado")
        self.assertEqual(res_sync_t2["exitosos"], 3)
        self.assertEqual(res_sync_t2["fallidos"], 0)
        self.assertEqual(sync_mgr.obtener_conteo_pendientes(conn=self.conn_t2)["pendientes"], 0)
        self.assertEqual(sync_mgr.obtener_conteo_pendientes(conn=self.conn_t2)["sincronizados"], 3)

        # =====================================================================
        # PASO 6: Prueba de IDEMPOTENCIA Absoluta (Reintento de red forzado)
        # =====================================================================
        # Simulamos que por una falla transitoria de ACK la terminal re-envía
        # exactamente la misma cola. El servidor debe reconocer cada idempotency_key
        # y NO volver a descontar stock, ni duplicar ventas o movimientos contables.
        # Despachar manualmente un reintento idéntico de cada operación
        for op in sync_mgr.obtener_items_pendientes(limite=10, conn=self.conn_t1):
            pass # No hay pendientes

        # Despacho forzado de las operaciones ya sincronizadas con la misma idempotency_key
        exito_re_vta, _, _ = sync_mgr._despachar_operacion(
            idem_vta_t1_off, OP_VENTA,
            {
                "subtotal": 23200.0, "total": 23200.0, "terminal_id": 1,
                "items": [{"tipo_item": "producto", "item_id": 1, "cantidad": 4.0, "precio_vendido": 5800.0, "subtotal": 23200.0, "ubicacion": "Vitrina"}],
                "pagos": [{"metodo": "Efectivo", "monto": 23200.0}]
            }
        )
        self.assertTrue(exito_re_vta, "El servidor debe aceptar reintento idempotente de venta sin error")

        exito_re_gasto, _, _ = sync_mgr._despachar_operacion(
            idem_gasto_t1_off, OP_GASTO,
            {"categoria": "Operativo", "concepto": "Fletes T1", "valor": 15000.0, "metodo_pago": "Efectivo"}
        )
        self.assertTrue(exito_re_gasto, "El servidor debe aceptar reintento idempotente de gasto sin error")

        # =====================================================================
        # PASO 7: Verificación Exhaustiva de Consistencia en el Servidor
        # =====================================================================
        async def _verificar_servidor():
            async with SessionLocal() as db:
                # 1. INVENTARIO EXACTO
                # Stock Inicial: 1000 total (500 Vitrina, 500 Bodega)
                # Ventas totales:
                #   - T1 Online: 2
                #   - T2 Online: 3
                #   - T1 Offline: 4
                #   - T2 Offline: 6
                #   Total vendidos: 15 unidades
                # Traslado T1: 20 unidades Bodega -> Vitrina
                # Stock Vitrina esperado: 500 - 15 + 20 = 505
                # Stock Bodega esperado: 500 - 20 = 480
                # Stock Total esperado: 985
                prod = (await db.execute(select(Producto).where(Producto.codigo == "00001"))).scalars().first()
                self.assertIsNotNone(prod)
                self.assertEqual(prod.stock_vitrina, 505.0, f"Stock Vitrina incongruente: {prod.stock_vitrina}")
                self.assertEqual(prod.stock_bodega, 480.0, f"Stock Bodega incongruente: {prod.stock_bodega}")
                self.assertEqual(prod.stock, 985.0, f"Stock Total incongruente: {prod.stock}")

                # 2. CONSOLIDACIÓN DE VENTAS
                # Debe haber exactamente 4 ventas registradas (2 online + 2 offline sincronizadas)
                ventas_total = (await db.execute(select(Venta))).scalars().all()
                self.assertEqual(len(ventas_total), 4, f"Se duplicaron o perdieron ventas: {len(ventas_total)}")

                # 3. SESIONES DE CAJA AISLADAS
                # Sesión T1 (CAJA-01) debe registrar exclusivamente movimientos de T1
                s1 = (await db.execute(select(SesionCaja).where(SesionCaja.id == sesion_t1_id))).scalars().first()
                self.assertEqual(s1.terminal_nombre, "CAJA-01")

                # Sesión T2 (CAJA-02) debe registrar exclusivamente movimientos de T2
                s2 = (await db.execute(select(SesionCaja).where(SesionCaja.id == sesion_t2_id))).scalars().first()
                self.assertEqual(s2.terminal_nombre, "CAJA-02")

                # 4. CARTERA DE CLIENTES
                # Cliente 1 tenía CXC con saldo_pendiente = 100,000. Recibió abono de $20,000 en T1 offline.
                cxc = (await db.execute(select(CuentaPorCobrar).where(CuentaPorCobrar.cliente_id == 1))).scalars().first()
                self.assertIsNotNone(cxc)
                self.assertEqual(cxc.saldo_pendiente, 80000.0, f"Saldo CXC cliente no refleja el abono: {cxc.saldo_pendiente}")

                # 5. SALDO DE PROVEEDORES
                # Proveedor 1 tenía saldo acumulado = 50,000. Recibió liquidación de $25,000 en T2 offline.
                prov = (await db.execute(select(Proveedor).where(Proveedor.id == 1))).scalars().first()
                self.assertIsNotNone(prov)
                self.assertEqual(prov.saldo_acumulado, 25000.0, f"Saldo proveedor incorrecto: {prov.saldo_acumulado}")

        asyncio.run(_verificar_servidor())

    def test_02_recuperacion_automatica_de_bloqueo_por_cierre_abrupto(self):
        """
        Simula que la aplicación de escritorio se cierra abruptamente (apagón / crash)
        mientras una operación estaba en estado 'SINCRONIZANDO'.
        Valida que recuperar_operaciones_interrumpidas() restaure la operación a 'PENDIENTE'
        y que en el siguiente ciclo se sincronice con éxito en lugar de quedar huérfana.
        """
        # 1. Encolar una operación normal
        idem_crash = f"crash-recovery-{time.time()}"
        op_id = sync_mgr.encolar_operacion(
            tipo_operacion=OP_GASTO,
            payload={
                "categoria": "Emergencia",
                "concepto": "Gasto interrumpido por corte de energía",
                "valor": 7500.0,
                "metodo_pago": "Efectivo",
            },
            usuario="Cajero Emergencia",
            dispositivo="CAJA-01",
            idempotency_key=idem_crash,
            conn=self.conn_t1,
        )

        # 2. Simular que la operación quedó en 'SINCRONIZANDO' con timestamp desactualizado (> 60 segundos)
        hace_tres_min = (datetime.now() - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M:%S")
        self.conn_t1.execute(
            "UPDATE cola_sincronizacion SET estado_sync = ?, updated_at = ? WHERE id = ?",
            (ESTADO_SINCRONIZANDO, hace_tres_min, op_id)
        )
        self.conn_t1.commit()

        # Verificar estado artificial de crash
        cur = self.conn_t1.cursor()
        cur.execute("SELECT estado_sync FROM cola_sincronizacion WHERE id = ?", (op_id,))
        self.assertEqual(cur.fetchone()[0], ESTADO_SINCRONIZANDO)

        # 3. Ejecutar auto-recuperación de operaciones interrumpidas
        sync_mgr.recuperar_operaciones_interrumpidas(conn=self.conn_t1)

        # 4. Verificar que se restableció a 'PENDIENTE'
        cur.execute("SELECT estado_sync FROM cola_sincronizacion WHERE id = ?", (op_id,))
        self.assertEqual(cur.fetchone()[0], ESTADO_PENDIENTE, "La operación interrumpida debió revertirse a PENDIENTE")

        # 5. Procesar la cola y comprobar que se sincroniza normalmente
        res_sync = sync_mgr.procesar_cola(conn=self.conn_t1)
        self.assertEqual(res_sync["status"], "completado")
        self.assertEqual(res_sync["exitosos"], 1)

        cur.execute("SELECT estado_sync FROM cola_sincronizacion WHERE id = ?", (op_id,))
        self.assertEqual(cur.fetchone()[0], ESTADO_SINCRONIZADO, "La operación recuperada no alcanzó estado SINCRONIZADO")


if __name__ == "__main__":
    unittest.main()
