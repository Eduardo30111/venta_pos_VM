#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pruebas de seguridad para activación inicial de administrador,
validación de contraseñas seguras y detección obligatoria de contraseñas por defecto.
"""

import unittest
import os
import tempfile
import sqlite3

# Configurar entorno de base de datos aislada
_temp_dir = tempfile.mkdtemp()
_test_db = os.path.join(_temp_dir, "test_usuarios_activacion.db")

from interface.usuarios_db import (
    crear_tablas_iniciales,
    hay_administrador,
    crear_administrador_inicial,
    validar_password_fuerte,
    inicializar_admin_default,
    obtener_usuario_por_credenciales,
    actualizar_usuario_db,
    hash_password,
    verificar_password,
)


class TestSeguridadActivacionAdmin(unittest.TestCase):
    def setUp(self):
        os.environ["VMPOS_DB_USUARIOS"] = _test_db
        if os.path.exists(_test_db):
            os.remove(_test_db)
        crear_tablas_iniciales()

    def tearDown(self):
        os.environ.pop("VMPOS_DB_USUARIOS", None)
        if os.path.exists(_test_db):
            os.remove(_test_db)

    def test_01_validacion_password_fuerte(self):
        """Valida que se rechacen contraseñas cortas o predeterminadas."""
        valido, msg = validar_password_fuerte("123")
        self.assertFalse(valido)
        self.assertIn("al menos 6", msg)

        valido, msg = validar_password_fuerte("admin123")
        self.assertFalse(valido)
        self.assertIn("predeterminada o insegura", msg)

        valido, msg = validar_password_fuerte("123456")
        self.assertFalse(valido)

        valido, msg = validar_password_fuerte("MiClaveSegura2026!")
        self.assertTrue(valido)
        self.assertEqual(msg, "")

    def test_02_activacion_primer_administrador(self):
        """Verifica el flujo de activación del primer administrador en sistema limpio."""
        self.assertFalse(hay_administrador())

        # Intentar crear con contraseña insegura
        with self.assertRaises(ValueError):
            crear_administrador_inicial("admin", "admin123")

        # Crear con contraseña válida
        ok = crear_administrador_inicial("gerente", "ClaveSegura2026*", nombre="Carlos", apellidos="Gómez")
        self.assertTrue(ok)
        self.assertTrue(hay_administrador())

        # Verificar login con credenciales creadas
        u = obtener_usuario_por_credenciales("gerente", "ClaveSegura2026*")
        self.assertIsNotNone(u)
        self.assertEqual(u["usuario"], "gerente")
        self.assertEqual(u["rol"], "Administrador")
        self.assertFalse(u["requiere_cambio_password"])

    def test_03_deteccion_admin_default_y_cambio_obligatorio(self):
        """Verifica que si existe un admin de fábrica con admin123, se marque para cambio obligatorio."""
        inicializar_admin_default(forzar_legacy=True)
        self.assertTrue(hay_administrador())

        u = obtener_usuario_por_credenciales("admin", "admin123")
        self.assertIsNotNone(u)
        self.assertTrue(u["requiere_cambio_password"])

        # Actualizar a una contraseña personalizada
        uid = u["id"]
        actualizar_usuario_db(uid, password="NuevaClaveSegura2026#")

        # Iniciar sesión con la nueva contraseña: ya no debe requerir cambio
        u_actualizado = obtener_usuario_por_credenciales("admin", "NuevaClaveSegura2026#")
        self.assertIsNotNone(u_actualizado)
        self.assertFalse(u_actualizado["requiere_cambio_password"])


if __name__ == "__main__":
    unittest.main()
