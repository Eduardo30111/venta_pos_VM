#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Suite de Pruebas para la Utilidad de Recuperación de Administrador:
- Generación de contraseñas temporales de 16 caracteres de alta entropía.
- Validación de política fuerte (mínimo 12 caracteres, mayúsculas, minúsculas, dígitos, símbolos).
- Listado seguro de administradores.
- Restablecimiento con contraseña explícita y forzado de cambio de contraseña en temporal.
"""

import unittest
import os
import shutil
import tempfile
import sqlite3

from scripts.recuperar_password_admin import (
    generar_password_temporal_segura,
    listar_administradores,
    restablecer_password_admin,
)
from interface.usuarios_db import (
    crear_tablas_iniciales,
    hash_password,
    obtener_usuario_por_credenciales,
    validar_password_fuerte,
)


class TestRecuperacionPasswordAdmin(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="test_recovery_admin_")
        self.db_path = os.path.join(self.temp_dir, "usuarios.db")
        self._orig_env = os.environ.get("VMPOS_DB_USUARIOS")
        os.environ["VMPOS_DB_USUARIOS"] = self.db_path

        crear_tablas_iniciales()

        # Insertar un administrador y un cajero
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO usuarios (usuario, password, rol, estado, nombre, apellidos, requiere_cambio_password) "
                "VALUES ('admin_principal', ?, 'Administrador', 'Activo', 'Carlos', 'Gómez', 0)",
                (hash_password("PasswordSegura2026!#"),)
            )
            cur.execute(
                "INSERT INTO usuarios (usuario, password, rol, estado, nombre, apellidos, requiere_cambio_password) "
                "VALUES ('cajero_turno', ?, 'Cajero', 'Activo', 'Luisa', 'Mora', 0)",
                (hash_password("CajeroTurno123!#"),)
            )

    def tearDown(self):
        if self._orig_env is not None:
            os.environ["VMPOS_DB_USUARIOS"] = self._orig_env
        else:
            os.environ.pop("VMPOS_DB_USUARIOS", None)
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_01_generacion_password_temporal(self):
        """Valida que la clave temporal generada tenga al menos 16 caracteres y cumpla la política fuerte."""
        clave = generar_password_temporal_segura(16)
        self.assertEqual(len(clave), 16)
        valido, msg = validar_password_fuerte(clave)
        self.assertTrue(valido, f"La clave temporal no cumplió la política: {msg}")

    def test_02_listar_administradores(self):
        """Valida que listar_administradores solo devuelva usuarios con rol Administrador."""
        admins = listar_administradores()
        self.assertEqual(len(admins), 1)
        self.assertEqual(admins[0][1], "admin_principal")

    def test_03_restablecer_con_clave_temporal_fuerza_cambio(self):
        """Valida que al generar temporal, se marque requiere_cambio_password = 1."""
        ok, clave_gen, msg = restablecer_password_admin("admin_principal", generar_temporal=True)
        self.assertTrue(ok)
        self.assertIsNotNone(clave_gen)
        self.assertEqual(len(clave_gen), 16)

        # Verificar que puede iniciar sesión con la clave temporal
        user_info = obtener_usuario_por_credenciales("admin_principal", clave_gen)
        self.assertIsNotNone(user_info)
        self.assertTrue(user_info["requiere_cambio_password"])

    def test_04_restablecer_con_clave_personalizada_valida(self):
        """Valida que una nueva clave personalizada de 12+ caracteres se guarde con requiere_cambio_password = 0."""
        nueva_clave = "MiClaveSuperSegura2026$#!"
        ok, clave_res, msg = restablecer_password_admin("admin_principal", nueva_clave=nueva_clave, generar_temporal=False)
        self.assertTrue(ok)
        self.assertEqual(clave_res, nueva_clave)

        user_info = obtener_usuario_por_credenciales("admin_principal", nueva_clave)
        self.assertIsNotNone(user_info)
        self.assertFalse(user_info["requiere_cambio_password"])

    def test_05_rechazar_restablecimiento_de_no_admin(self):
        """No permite restablecer credenciales de un rol no-administrador mediante esta utilidad."""
        ok, _, msg = restablecer_password_admin("cajero_turno", generar_temporal=True)
        self.assertFalse(ok)
        self.assertIn("solo aplica a administradores", msg)


if __name__ == "__main__":
    unittest.main()
