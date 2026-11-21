#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas de Seguridad Integral, Control de Acceso Basado en Roles (RBAC),
Revocación de Sesiones y Trazabilidad de Auditoría para VmPOS.
"""

import unittest
import asyncio
import os
import time
from httpx import AsyncClient, ASGITransport
from sqlalchemy.future import select

from server.main import app
from server.database import SessionLocal
from server.models.usuario import Usuario
from server.models.auditoria import AuditLog
from server.middleware.auth import hash_password, validar_password_fuerte_servidor
from tests.test_helpers import init_isolated_test_db, cleanup_isolated_test_db


class TestSeguridadRBACyAuditoria(unittest.TestCase):
    test_db = f"/tmp/test_rbac_auditoria_{os.getpid()}.db"

    @classmethod
    def setUpClass(cls):
        asyncio.run(init_isolated_test_db(cls.test_db))
        cls.transport = ASGITransport(app=app)
        asyncio.run(cls._seed_usuarios())

    @classmethod
    async def _seed_usuarios(cls):
        from server.models.cliente import Cliente
        async with SessionLocal() as db:
            # 1. Operario sin privilegios administrativos
            res_op = await db.execute(select(Usuario).where(Usuario.usuario == "operario_test"))
            if not res_op.scalars().first():
                db.add(Usuario(
                    id=2,
                    usuario="operario_test",
                    password_hash=hash_password("Operario2026*"),
                    nombre="Pedro",
                    apellidos="Operario",
                    rol="Operario",
                    estado="Activo",
                    porcentaje_comision=5.0,
                ))

            # 2. Cliente para prueba de límite de crédito
            res_cli = await db.execute(select(Cliente).where(Cliente.id == 1))
            if not res_cli.scalars().first():
                db.add(Cliente(
                    id=1,
                    nombre="Cliente Test",
                    documento="12345678",
                    limite_credito=10000.0,
                    permite_fiado=True,
                    estado="Activo"
                ))
            await db.commit()

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cleanup_isolated_test_db(cls.test_db))

    def test_01_politica_password_fuerte_servidor(self):
        """Valida que el servidor rechace contraseñas de menos de 12 caracteres, débiles o predeterminadas."""
        valido, msg = validar_password_fuerte_servidor("123")
        self.assertFalse(valido)
        self.assertIn("al menos 12", msg)

        # 8 caracteres (falla política de 12)
        valido, msg = validar_password_fuerte_servidor("Clave123!")
        self.assertFalse(valido)
        self.assertIn("al menos 12", msg)

        valido, msg = validar_password_fuerte_servidor("admin123")
        self.assertFalse(valido)

        valido, msg = validar_password_fuerte_servidor("123456789012")
        self.assertFalse(valido)

        # 12 caracteres pero sin minúscula
        valido, msg = validar_password_fuerte_servidor("CLAVE123456!")
        self.assertFalse(valido)
        self.assertIn("minúscula", msg)

        # 12 caracteres pero sin números
        valido, msg = validar_password_fuerte_servidor("ClaveSinNum!")
        self.assertFalse(valido)
        self.assertIn("número", msg)

        # Válida con 12+ caracteres y alta entropía
        valido, msg = validar_password_fuerte_servidor("ClaveSuperSegura2026#")
        self.assertTrue(valido)
        self.assertEqual(msg, "")

    def test_02_rbac_bloqueo_rutas_administrativas_a_operarios(self):
        """Verifica que usuarios sin rol Administrador reciban 403 en rutas protegidas."""
        async def _run():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # Login como Operario
                res_op = await client.post("/auth/login", json={"usuario": "operario_test", "password": "Operario2026*", "terminal_id": 1})
                self.assertEqual(res_op.status_code, 200)
                op_token = res_op.json()["access_token"]
                op_headers = {"Authorization": f"Bearer {op_token}"}

                # 1. Listar usuarios -> 403
                res_usr_list = await client.get("/usuarios", headers=op_headers)
                self.assertEqual(res_usr_list.status_code, 403)

                # 2. Crear usuario -> 403
                res_usr_new = await client.post("/usuarios", json={"usuario": "hacker", "password": "Password123#", "rol": "Administrador"}, headers=op_headers)
                self.assertEqual(res_usr_new.status_code, 403)

                # 3. Eliminar usuario -> 403
                res_usr_del = await client.delete("/usuarios/1", headers=op_headers)
                self.assertEqual(res_usr_del.status_code, 403)

                # 4. Modificar configuración de negocio -> 403
                res_cfg = await client.put("/configuracion/negocio", json={"nombre_negocio": "Hackeado POS"}, headers=op_headers)
                self.assertEqual(res_cfg.status_code, 403)

                # 5. Crear categoría -> 403
                res_cat = await client.post("/categorias", json={"nombre": "Categoria Hack"}, headers=op_headers)
                self.assertEqual(res_cat.status_code, 403)

                # 6. Modificar límite de crédito de cliente -> 403
                res_cli_cred = await client.put("/clientes/1", json={"limite_credito": 999999.0}, headers=op_headers)
                self.assertEqual(res_cli_cred.status_code, 403)
                self.assertIn("solo un administrador", res_cli_cred.text.lower())

        asyncio.run(_run())

    def test_03_revocacion_jwt_logout(self):
        """Verifica que /auth/logout invalide efectivamente el token JWT (jti)."""
        async def _run():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # Login como Admin
                res_login = await client.post("/auth/login", json={"usuario": "admin", "password": "123456", "terminal_id": 1})
                self.assertEqual(res_login.status_code, 200)
                token = res_login.json()["access_token"]
                headers = {"Authorization": f"Bearer {token}"}

                # Probar acceso exitoso antes de logout
                res_check = await client.get("/auth/me", headers=headers)
                self.assertEqual(res_check.status_code, 200)

                # Ejecutar logout
                res_logout = await client.post("/auth/logout", headers=headers)
                self.assertEqual(res_logout.status_code, 200)
                self.assertIn("Sesion cerrada", res_logout.json().get("message", ""))

                # Intentar usar el mismo token después del logout -> Debe ser 401
                res_check_after = await client.get("/auth/me", headers=headers)
                self.assertEqual(res_check_after.status_code, 401)
                self.assertIn("Sesión cerrada", res_check_after.text)

        asyncio.run(_run())

    def test_04_trazabilidad_auditoria_en_operaciones(self):
        """Verifica que las operaciones administrativas y financieras persistan en audit_log."""
        async def _run():
            async with AsyncClient(transport=self.transport, base_url="http://test") as client:
                # Login como Admin
                res_login = await client.post("/auth/login", json={"usuario": "admin", "password": "123456", "terminal_id": 1})
                self.assertEqual(res_login.status_code, 200)
                headers = {"Authorization": f"Bearer {res_login.json()['access_token']}"}

                # Registrar un gasto
                payload_gasto = {
                    "categoria": "Servicios",
                    "concepto": "Pago de Internet Fibra Óptica Auditoría",
                    "valor": 95000.0,
                    "metodo_pago": "Efectivo",
                    "idempotency_key": f"audit-gasto-{time.time()}"
                }
                res_gasto = await client.post("/gastos", json=payload_gasto, headers=headers)
                self.assertEqual(res_gasto.status_code, 200)

                # Verificar registro en tabla audit_log
                async with SessionLocal() as db:
                    logs = (await db.execute(
                        select(AuditLog).where(AuditLog.modulo == "GASTOS", AuditLog.accion == "CREAR")
                    )).scalars().all()
                    self.assertTrue(len(logs) > 0, "No se encontró registro de auditoría para GASTOS/CREAR")
                    ultimo = logs[-1]
                    self.assertIn("Administrador", ultimo.usuario_nombre)
                    self.assertIn("95000", str(ultimo.valor_nuevo))

        asyncio.run(_run())


if __name__ == "__main__":
    unittest.main()
