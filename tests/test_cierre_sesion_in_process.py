#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests automatizados para Cierre de Sesión In-Process, Aislamiento de Permisos entre Usuarios
y Cierre Definitivo del Sistema en VmPOS.
Archivo: tests/test_cierre_sesion_in_process.py
"""

import unittest
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.session_manager import session_mgr
from interface.menu_inicio import VmPOSDashboard
from client.api_client import api


class TestCierreSesionInProcess(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        self.login_window = tk.Toplevel(self.root)
        self.login_window.title("Inicio de Sesión - Test")
        self.login_window.withdraw()
        session_mgr.registrar_login_window(self.login_window)

    def tearDown(self):
        try:
            if self.login_window and self.login_window.winfo_exists():
                self.login_window.destroy()
        except Exception:
            pass

    def test_01_cerrar_sesion_in_process_restaura_login(self):
        """Verifica que cerrar_sesion destruya el dashboard y restaure la ventana de login in-process."""
        # 1. Simular login de Admin
        dash = VmPOSDashboard(
            usuario="AdminTest",
            datos_usuario={"id": 1, "rol": "administrador", "nombre": "Administrador"},
            parent=self.login_window
        )
        session_mgr.iniciar_sesion("AdminTest", "administrador", 1, token="test_jwt_token_123")
        self.assertTrue(session_mgr.sesion_activa)
        self.assertEqual(session_mgr.usuario_actual, "AdminTest")
        self.assertEqual(os.environ.get("VMPOS_TOKEN"), "test_jwt_token_123")

        # 2. Ejecutar cierre de sesión con retorno al login (lanzar_login=True)
        session_mgr.cerrar_sesion(root_window=dash, lanzar_login=True, login_window=self.login_window)

        # 3. Validar estado de sesión completamente limpio
        self.assertFalse(session_mgr.sesion_activa, "La sesión no debe quedar activa")
        self.assertIsNone(api.token, "El token de API debe ser revocado y limpiado")
        self.assertNotIn("VMPOS_TOKEN", os.environ, "La variable VMPOS_TOKEN debe ser removida de entorno")

        # 4. Validar que el dashboard fue destruido y la ventana de login sigue viva y visible
        self.assertFalse(dash.winfo_exists(), "El dashboard debe ser destruido al cerrar sesión")
        self.assertTrue(self.login_window.winfo_exists(), "La ventana de login debe mantenerse viva en el proceso")
        self.assertEqual(self.login_window.state(), "normal", "La ventana de login debe estar en estado normal")

    def test_02_aislamiento_de_roles_usuario_a_vs_usuario_b(self):
        """Verifica que al cambiar de usuario no queden residuos de permisos ni credenciales."""
        # Usuario A: Administrador
        dash_a = VmPOSDashboard(
            usuario="AdminA",
            datos_usuario={"id": 10, "rol": "administrador"},
            parent=self.login_window
        )
        self.assertEqual(dash_a.rol_usuario, "administrador")
        self.assertEqual(dash_a.permisos.get("Inventario"), 1)
        self.assertEqual(dash_a.permisos.get("Usuarios"), 1)
        self.assertEqual(dash_a.permisos.get("Contabilidad"), 1)

        # Cerrar sesión de Usuario A
        session_mgr.cerrar_sesion(root_window=dash_a, lanzar_login=True, login_window=self.login_window)

        # Usuario B: Operario / Vendedor
        dash_b = VmPOSDashboard(
            usuario="OperarioB",
            datos_usuario={"id": 20, "rol": "operario"},
            parent=self.login_window
        )
        self.assertEqual(dash_b.rol_usuario, "operario")
        self.assertEqual(dash_b.permisos.get("Inventario"), 0, "Operario no debe tener acceso a Inventario")
        self.assertEqual(dash_b.permisos.get("Usuarios"), 0, "Operario no debe tener acceso a Usuarios")
        self.assertEqual(dash_b.permisos.get("Contabilidad"), 0, "Operario no debe tener acceso a Contabilidad")
        self.assertEqual(dash_b.permisos.get("Ventas"), 1)

        dash_b.destroy()

    def test_03_salir_del_sistema_cierra_todo(self):
        """Verifica que salir_sistema (lanzar_login=False) destruya dashboard y login."""
        dash = VmPOSDashboard(
            usuario="UserExit",
            datos_usuario={"id": 30, "rol": "vendedor"},
            parent=self.login_window
        )
        # Salir del sistema
        session_mgr.cerrar_sesion(root_window=dash, lanzar_login=False, login_window=self.login_window)

        self.assertFalse(dash.winfo_exists())
        self.assertFalse(self.login_window.winfo_exists())


if __name__ == "__main__":
    unittest.main()
