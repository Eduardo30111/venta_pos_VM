#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_cambio_fecha_hora_ventas.py
Suite de pruebas exhaustivas para validar la corrección del cambio de fecha y hora
en el módulo de Gestión y Supervisión de Ventas de VmPOS.

Casos verificados:
1. Modificar solo la fecha (la hora debe quedar intacta).
2. Modificar solo la hora (la fecha debe quedar intacta).
3. Modificar fecha y hora simultáneamente.
4. Modificar de hora de la mañana a la tarde (08:30 a. m. -> 06:45 p. m. / 18:45:00).
5. Modificar de hora de la tarde a la mañana (06:45 p. m. -> 08:30 a. m. / 08:30:00).
6. Cerrar modal, volver a consultar la venta y verificar que la nueva hora se mantenga.
7. Cerrar VmPOS, reabrir conexión a base de datos y verificar persistencia en SQLite y servidor.
8. Sincronización entre terminales y API: el backend FastAPI/SQLAlchemy persiste y entrega fecha y hora modificadas.
9. Impacto contable y no alteración de caja física: el arqueo físico de caja permanece intacto y fecha_registro inmutable.
"""

import os
import sys
import unittest
import sqlite3
import tempfile
import asyncio
from datetime import datetime

# Asegurar path de importación
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from interface.ventas_admin_dialog import _normalizar_fecha, _normalizar_hora, _formatear_hora_display
from interface.caja_manager import editar_venta_completa, normalizar_hora as cm_normalizar_hora, normalizar_fecha as cm_normalizar_fecha
from interface.database_manager import conectar_db, inicializar_base_datos

try:
    from server.services.venta_service import normalizar_hora as srv_normalizar_hora, normalizar_fecha as srv_normalizar_fecha, VentaService
    from server.schemas.venta import EditarVentaRequest, EditarVentaItemRequest
    from server.database import get_db, Base, engine, SessionLocal, asegurar_migraciones_sqlite
    from server.models.usuario import Usuario
    from server.models.venta import Venta, DetalleVenta
    from server.models.terminal import Terminal
    from server.models.caja import SesionCaja
    from sqlalchemy.future import select
    HAS_SERVER_DEPS = True
except ImportError:
    HAS_SERVER_DEPS = False


class TestCambioFechaHoraVentas(unittest.TestCase):
    """Pruebas unitarias e integrales para el cambio independiente de fecha y hora de ventas."""

    @classmethod
    def setUpClass(cls):
        inicializar_base_datos()
        try:
            asegurar_migraciones_sqlite()
        except Exception:
            pass

    def setUp(self):
        self.conn = conectar_db()
        self.cur = self.conn.cursor()

        # Asegurar columnas necesarias en ventas
        self.cur.execute("PRAGMA table_info(ventas)")
        cols = [c[1] for c in self.cur.fetchall()]
        if "fecha_registro" not in cols:
            self.cur.execute("ALTER TABLE ventas ADD COLUMN fecha_registro TEXT")
        if "es_venta_atrasada" not in cols:
            self.cur.execute("ALTER TABLE ventas ADD COLUMN es_venta_atrasada INTEGER DEFAULT 0")
        if "motivo_modificacion_fecha" not in cols:
            self.cur.execute("ALTER TABLE ventas ADD COLUMN motivo_modificacion_fecha TEXT")
        if "fecha_modificacion" not in cols:
            self.cur.execute("ALTER TABLE ventas ADD COLUMN fecha_modificacion TEXT")
        if "modificado_por" not in cols:
            self.cur.execute("ALTER TABLE ventas ADD COLUMN modificado_por TEXT")
        self.conn.commit()

        # Insertar venta de prueba con fecha y hora iniciales: 2026-11-21 08:30:00
        self.fecha_orig = "2026-11-21"
        self.hora_orig = "08:30:00"
        self.fecha_registro_orig = "2026-11-21 08:30:00"

        # Asegurar producto de prueba
        self.cur.execute("""
            INSERT OR REPLACE INTO productos (codigo, nombre, precio, stock, stock_vitrina, stock_bodega, tipo_producto)
            VALUES ('TEST-ITEM-FH', 'Producto Fecha Hora Test', 50000, 20, 20, 0, 'Producto')
        """)

        # Insertar venta
        self.cur.execute("""
            INSERT INTO ventas (
                fecha_venta, hora_venta, documento_cliente, total_venta, metodo_pago, operario, estado, fecha_registro
            ) VALUES (?, ?, 'CC-12345', 50000, 'Efectivo', 'AdminTest', 'Completada', ?)
        """, (self.fecha_orig, self.hora_orig, self.fecha_registro_orig))
        self.id_venta = self.cur.lastrowid

        # Insertar detalle
        self.cur.execute("""
            INSERT INTO detalle_ventas (
                id_venta, codigo_producto, nombre_producto, precio_unitario, cantidad, subtotal, costo_unitario
            ) VALUES (?, 'TEST-ITEM-FH', 'Producto Fecha Hora Test', 50000, 1, 50000, 25000)
        """, (self.id_venta,))

        self.conn.commit()

    def tearDown(self):
        try:
            self.cur.execute("DELETE FROM detalle_ventas WHERE id_venta = ?", (self.id_venta,))
            self.cur.execute("DELETE FROM ventas WHERE id_venta = ?", (self.id_venta,))
            self.cur.execute("DELETE FROM auditoria_ventas WHERE id_venta = ?", (self.id_venta,))
            self.conn.commit()
        except Exception:
            pass
        finally:
            self.conn.close()

    # =========================================================================
    # CASO 1: MODIFICAR SOLO LA FECHA (LA HORA DEBE QUEDAR INTACTA)
    # =========================================================================
    def test_01_modificar_solo_fecha_hora_intacta(self):
        """Valida que modificar únicamente la fecha conserve exactamente la hora original."""
        nueva_f = "2026-11-20"
        res = editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{
                "codigo_producto": "TEST-ITEM-FH",
                "nombre_producto": "Producto Fecha Hora Test",
                "precio_unitario": 50000,
                "cantidad": 1
            }],
            motivo="Corrección de fecha operativa",
            nueva_fecha=nueva_f,
            nueva_hora=None  # No se modifica la hora
        )
        self.assertTrue(res.get("ok") or res.get("success") or res.get("exito"))

        # Consultar venta en base de datos
        self.cur.execute("SELECT fecha_venta, hora_venta, estado FROM ventas WHERE id_venta = ?", (self.id_venta,))
        row = self.cur.fetchone()
        self.assertEqual(row[0], nueva_f, "La fecha debe haber cambiado a 2026-11-20")
        self.assertEqual(row[1], self.hora_orig, "La hora debe haber quedado exactamente intacta en 08:30:00")
        self.assertEqual(row[2], "Modificada")

    # =========================================================================
    # CASO 2: MODIFICAR SOLO LA HORA (LA FECHA DEBE QUEDAR INTACTA)
    # =========================================================================
    def test_02_modificar_solo_hora_fecha_intacta(self):
        """Valida que modificar únicamente la hora conserve exactamente la fecha original."""
        nueva_h_input = "06:45 p. m."  # Formato 12 horas en español con a. m. / p. m.
        res = editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{
                "codigo_producto": "TEST-ITEM-FH",
                "nombre_producto": "Producto Fecha Hora Test",
                "precio_unitario": 50000,
                "cantidad": 1
            }],
            motivo="Ajuste de hora según ticket manual",
            nueva_fecha=None,  # No se modifica la fecha
            nueva_hora=nueva_h_input
        )
        self.assertTrue(res.get("ok") or res.get("success") or res.get("exito"))

        self.cur.execute("SELECT fecha_venta, hora_venta FROM ventas WHERE id_venta = ?", (self.id_venta,))
        row = self.cur.fetchone()
        self.assertEqual(row[0], self.fecha_orig, "La fecha debe haber quedado intacta en 2026-11-21")
        self.assertEqual(row[1], "18:45:00", "La hora normalizada en BD debe ser 18:45:00")
        self.assertEqual(_formatear_hora_display(row[1]), "06:45 p. m.", "La hora presentada al usuario debe ser 06:45 p. m.")

    # =========================================================================
    # CASO 3: MODIFICAR FECHA Y HORA AL MISMO TIEMPO
    # =========================================================================
    def test_03_modificar_fecha_y_hora_simultaneamente(self):
        """Valida que modificar fecha y hora al mismo tiempo persista ambos valores."""
        nueva_f = "2026-11-20"
        nueva_h = "06:45 p. m."

        res = editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{
                "codigo_producto": "TEST-ITEM-FH",
                "nombre_producto": "Producto Fecha Hora Test",
                "precio_unitario": 50000,
                "cantidad": 1
            }],
            motivo="Modificación simultánea fecha y hora",
            nueva_fecha=nueva_f,
            nueva_hora=nueva_h
        )
        self.assertTrue(res.get("ok") or res.get("success") or res.get("exito"))

        self.cur.execute("SELECT fecha_venta, hora_venta FROM ventas WHERE id_venta = ?", (self.id_venta,))
        row = self.cur.fetchone()
        self.assertEqual(row[0], "2026-11-20", "La fecha debe ser 2026-11-20")
        self.assertEqual(row[1], "18:45:00", "La hora en BD debe ser 18:45:00")
        self.assertEqual(_formatear_hora_display(row[1]), "06:45 p. m.")

    # =========================================================================
    # CASO 4: MODIFICAR DE HORA DE LA MAÑANA A LA TARDE (08:30 a. m. -> 06:45 p. m.)
    # =========================================================================
    def test_04_modificar_de_manana_a_tarde(self):
        """Aceptación explícita: de 08:30 a. m. a 06:45 p. m."""
        # Verificar estado inicial
        self.assertEqual(_formatear_hora_display(self.hora_orig), "08:30 a. m.")

        # Modificar a 06:45 p. m.
        editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{"codigo_producto": "TEST-ITEM-FH", "nombre_producto": "Prod", "precio_unitario": 50000, "cantidad": 1}],
            motivo="Cambio mañana a tarde",
            nueva_hora="06:45 p. m."
        )

        self.cur.execute("SELECT hora_venta FROM ventas WHERE id_venta = ?", (self.id_venta,))
        h_bd = self.cur.fetchone()[0]
        self.assertEqual(h_bd, "18:45:00")
        self.assertEqual(_formatear_hora_display(h_bd), "06:45 p. m.")

    # =========================================================================
    # CASO 5: MODIFICAR DE HORA DE LA TARDE A LA MAÑANA (06:45 p. m. -> 08:30 a. m.)
    # =========================================================================
    def test_05_modificar_de_tarde_a_manana(self):
        """Valida transición inversa: de 06:45 p. m. a 08:30 a. m."""
        # Establecer primero tarde
        self.cur.execute("UPDATE ventas SET hora_venta = '18:45:00' WHERE id_venta = ?", (self.id_venta,))
        self.conn.commit()

        # Modificar a mañana
        editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{"codigo_producto": "TEST-ITEM-FH", "nombre_producto": "Prod", "precio_unitario": 50000, "cantidad": 1}],
            motivo="Reversión a hora matutina",
            nueva_hora="08:30 a. m."
        )

        self.cur.execute("SELECT hora_venta FROM ventas WHERE id_venta = ?", (self.id_venta,))
        h_bd = self.cur.fetchone()[0]
        self.assertEqual(h_bd, "08:30:00")
        self.assertEqual(_formatear_hora_display(h_bd), "08:30 a. m.")

    # =========================================================================
    # CASO 6: CERRAR MODAL, RECONSULTAR Y VERIFICAR QUE LA NUEVA HORA SE MANTENGA
    # =========================================================================
    def test_06_persistencia_modal_y_reconsulta(self):
        """Valida que al simular el cierre del modal y recargar la venta, se cargue '06:45 p. m.'."""
        editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{"codigo_producto": "TEST-ITEM-FH", "nombre_producto": "Prod", "precio_unitario": 50000, "cantidad": 1}],
            motivo="Persistencia modal",
            nueva_fecha="2026-11-20",
            nueva_hora="06:45 p. m."
        )

        # Simular nueva consulta de la venta (como hace cargar_ventas y abrir_modal_editar)
        self.cur.execute("SELECT id_venta, fecha_venta, hora_venta FROM ventas WHERE id_venta = ?", (self.id_venta,))
        row = self.cur.fetchone()
        id_v, f_v, h_v = row[0], row[1], row[2]

        # Simular Treeview
        tree_hora_display = _formatear_hora_display(h_v)
        self.assertEqual(tree_hora_display, "06:45 p. m.")

        # Simular apertura de modal de edición que lee `vals[3]` del Treeview
        modal_hora_inicial = _formatear_hora_display(tree_hora_display)
        self.assertEqual(modal_hora_inicial, "06:45 p. m.", "El modal de edición debe abrirse mostrando exactamente '06:45 p. m.'")

    # =========================================================================
    # CASO 7: CERRAR VmPOS, REINICIAR Y COMPROBAR PERSISTENCIA EN DB
    # =========================================================================
    def test_07_persistencia_tras_reinicio_sistema(self):
        """Valida que cerrando completamente la conexión y abriendo una nueva, los datos persisten."""
        editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",
            nuevos_items=[{"codigo_producto": "TEST-ITEM-FH", "nombre_producto": "Prod", "precio_unitario": 50000, "cantidad": 1}],
            motivo="Prueba de reinicio",
            nueva_fecha="2026-11-20",
            nueva_hora="18:45:00"
        )

        # Simular cierre total de la aplicación cerrando la conexión
        self.conn.close()

        # Simular nuevo arranque de VmPOS con conexión fresca
        nueva_conn = conectar_db()
        try:
            nueva_cur = nueva_conn.cursor()
            nueva_cur.execute("SELECT fecha_venta, hora_venta, modificado_por, fecha_modificacion FROM ventas WHERE id_venta = ?", (self.id_venta,))
            r = nueva_cur.fetchone()
            self.assertEqual(r[0], "2026-11-20")
            self.assertEqual(r[1], "18:45:00")
            self.assertEqual(_formatear_hora_display(r[1]), "06:45 p. m.")
            self.assertEqual(r[2], "AdminAuditor")
            self.assertIsNotNone(r[3], "Debe registrarse timestamp de modificación")
        finally:
            nueva_conn.close()
            # Restaurar self.conn para tearDown
            self.conn = conectar_db()
            self.cur = self.conn.cursor()

    # =========================================================================
    # CASO 8: SINCRONIZACIÓN ENTRE TERMINALES Y MODELO DE SERVIDOR
    # =========================================================================
    def test_08_sincronizacion_entre_terminales_y_api(self):
        """Valida que el servicio del servidor (FastAPI / SQLAlchemy) procesa y sincroniza la hora correctamente."""
        if not HAS_SERVER_DEPS:
            self.skipTest("Dependencias de servidor (sqlalchemy) no instaladas en este entorno")
        async def _test_async_server_sync():
            async with SessionLocal() as session:
                # 0. Asegurar terminal y usuario en servidor
                res_term = await session.execute(select(Terminal).where(Terminal.id == 1))
                if not res_term.scalars().first():
                    session.add(Terminal(id=1, nombre="Terminal-1", activa=True))
                    await session.commit()

                res_u = await session.execute(select(Usuario).where(Usuario.id == 1))
                u_admin = res_u.scalars().first()
                if not u_admin:
                    u_admin = Usuario(id=1, usuario="admin_sync", rol="administrador", activo=True)
                    session.add(u_admin)
                    await session.commit()

                # 1. Crear venta en servidor
                v_srv = Venta(
                    numero=f"V-SRV-{self.id_venta}",
                    fecha="2026-11-21",
                    hora="08:30:00",
                    usuario_id=1,
                    terminal_id=1,
                    subtotal=50000,
                    total=50000,
                    metodo_pago_principal="Efectivo",
                    estado="Completada"
                )
                session.add(v_srv)
                await session.commit()
                await session.refresh(v_srv)

                # 2. Petición de edición cambiando fecha a 2026-11-20 y hora a '06:45 p. m.'
                req = EditarVentaRequest(
                    nuevo_metodo="Efectivo",
                    nuevos_items=[EditarVentaItemRequest(
                        codigo_producto="TEST-ITEM-FH",
                        nombre_producto="Prod",
                        precio_unitario=50000,
                        cantidad=1
                    )],
                    motivo="Sincronización multi-terminal",
                    nueva_fecha="2026-11-20",
                    nueva_hora="06:45 p. m."
                )

                # 3. Ejecutar edición
                res = await VentaService.editar_venta(
                    db=session,
                    venta_id=v_srv.id,
                    req=req,
                    usuario_id=1,
                    usuario=u_admin
                )

                self.assertTrue(res.get("ok"))
                self.assertEqual(res.get("fecha"), "2026-11-20")
                self.assertEqual(res.get("hora"), "18:45:00")

                # 4. Simular otra terminal consultando la venta
                res_q = await session.execute(select(Venta).where(Venta.id == v_srv.id))
                v_recibida = res_q.scalars().first()
                self.assertEqual(v_recibida.fecha, "2026-11-20")
                self.assertEqual(v_recibida.hora, "18:45:00")
                self.assertEqual(_formatear_hora_display(v_recibida.hora), "06:45 p. m.")

                # Limpieza
                await session.delete(v_recibida)
                await session.commit()

        asyncio.run(_test_async_server_sync())

    # =========================================================================
    # CASO 9: IMPACTO EN CIERRE DE CAJA Y FECHA DE REGISTRO INMUTABLE
    # =========================================================================
    def test_09_preservacion_arqueo_caja_y_fecha_registro_inmutable(self):
        """Valida que modificar fecha/hora no altere arqueo físico de caja y preserve fecha_registro."""
        # 1. Contar movimientos en movimientos_caja antes
        self.cur.execute("PRAGMA table_info(movimientos_caja)")
        cols_mc = [c[1] for c in self.cur.fetchall()]
        col_ref = "referencia_id" if "referencia_id" in cols_mc else "id_referencia"

        self.cur.execute(f"SELECT COUNT(*) FROM movimientos_caja WHERE {col_ref} = ?", (str(self.id_venta),))
        cnt_mov_antes = self.cur.fetchone()[0]

        # 2. Modificar solo fecha y hora
        editar_venta_completa(
            id_venta=self.id_venta,
            usuario_admin="AdminAuditor",
            nuevo_metodo="Efectivo",  # Mismo método
            nuevos_items=[{
                "codigo_producto": "TEST-ITEM-FH",
                "nombre_producto": "Producto Fecha Hora Test",
                "precio_unitario": 50000,
                "cantidad": 1  # Mismo monto
            }],
            motivo="Cambio temporal sin alterar físico de caja",
            nueva_fecha="2026-11-20",
            nueva_hora="06:45 p. m."
        )

        # 3. Contar movimientos después: no debe haber ningún nuevo movimiento porque el efectivo físico es idéntico
        self.cur.execute(f"SELECT COUNT(*) FROM movimientos_caja WHERE {col_ref} = ?", (str(self.id_venta),))
        cnt_mov_despues = self.cur.fetchone()[0]
        self.assertEqual(cnt_mov_despues, cnt_mov_antes, "No deben crearse movimientos de ajuste de caja cuando el monto no cambia")

        # 4. Verificar fecha_registro inmutable vs fecha_venta actualizada
        self.cur.execute("SELECT fecha_venta, hora_venta, fecha_registro, es_venta_atrasada FROM ventas WHERE id_venta = ?", (self.id_venta,))
        row = self.cur.fetchone()
        f_v, h_v, f_reg, es_atr = row[0], row[1], row[2], row[3]

        self.assertEqual(f_v, "2026-11-20", "La fecha operativa cambió a 2026-11-20")
        self.assertEqual(h_v, "18:45:00", "La hora operativa cambió a 18:45:00")
        self.assertEqual(f_reg, self.fecha_registro_orig, "La fecha de registro física original debe ser 100% INMUTABLE")
        self.assertEqual(es_atr, 1, "Debe quedar marcada como venta atrasada / fecha modificada")

        # 5. Verificar auditoría registrada
        self.cur.execute("SELECT accion, usuario, motivo FROM auditoria_ventas WHERE id_venta = ?", (self.id_venta,))
        aud = self.cur.fetchone()
        self.assertIsNotNone(aud, "Debe existir registro en auditoria_ventas")
        self.assertEqual(aud[0], "EDICION")
        self.assertEqual(aud[1], "AdminAuditor")


if __name__ == "__main__":
    unittest.main()
