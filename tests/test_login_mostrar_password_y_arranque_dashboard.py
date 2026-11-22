#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test Suite: Verificación de 'Mostrar Contraseña' en Login, Despliegue de Pantalla de Carga y Apertura Confiable del Dashboard.
Archivo: tests/test_login_mostrar_password_y_arranque_dashboard.py
"""

import os
import sys
import unittest
import tkinter as tk
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.database_manager import inicializar_base_datos, conectar_db
from interface.usuarios_db import crear_tablas_iniciales, insertar_usuario, obtener_usuario_por_credenciales
from interface.pantalla_carga import mostrar_carga, reproducir_bienvenida_asincrona, generar_saludo_bienvenida
from interface.menu_inicio import VmPOSDashboard, iniciar_dashboard
from interface.session_manager import session_mgr
import interface.inicio_sesion as login_mod


class TestLoginMostrarPasswordYArranqueDashboard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["VMPOS_TEST_MODE"] = "1"
        inicializar_base_datos()
        crear_tablas_iniciales()

        # Ocultar la ventana de login para pruebas desatendidas
        try:
            login_mod.ventana.withdraw()
        except Exception:
            pass

        # Crear usuarios de prueba específicos para cada rol si no existen
        try:
            insertar_usuario("admin_test_flow", "AdminPassword123#", "Administrador", nombre="Admin Tester")
        except Exception:
            pass
        try:
            insertar_usuario("vendedor_test_flow", "VendedorPass123#", "Vendedor", nombre="Vendedor Tester")
        except Exception:
            pass
        try:
            insertar_usuario("operario_test_flow", "OperarioPass123#", "Operario", nombre="Operario Tester")
        except Exception:
            pass

    @classmethod
    def tearDownClass(cls):
        try:
            login_mod.ventana.destroy()
        except Exception:
            pass

    def test_01_toggle_mostrar_ocultar_contrasena(self):
        """Prueba A: Alternar visibilidad de contraseña en el login sin alterar el contenido."""
        # Verificar widgets creados
        self.assertTrue(hasattr(login_mod, "entry_pass"), "El campo entry_pass debe existir")
        self.assertTrue(hasattr(login_mod, "lbl_toggle_pass"), "El control lbl_toggle_pass debe existir")
        self.assertTrue(hasattr(login_mod, "alternar_mostrar_contrasena"), "La función de toggle debe existir")

        # Estado inicial: oculto con asterisco
        login_mod.pass_var.set("MiClaveSuperSegura2026!")
        login_mod.entry_pass.config(show="*")
        login_mod.lbl_toggle_pass.config(text="👁️ Mostrar contraseña")

        self.assertEqual(login_mod.entry_pass.cget("show"), "*")
        self.assertEqual(login_mod.pass_var.get(), "MiClaveSuperSegura2026!")

        # Primer toggle: Mostrar
        login_mod.alternar_mostrar_contrasena()
        self.assertEqual(login_mod.entry_pass.cget("show"), "", "Al pulsar debe mostrar texto plano")
        self.assertIn("Ocultar contraseña", login_mod.lbl_toggle_pass.cget("text"))
        self.assertEqual(login_mod.pass_var.get(), "MiClaveSuperSegura2026!", "El texto no debe cambiar al mostrar")

        # Segundo toggle: Ocultar
        login_mod.alternar_mostrar_contrasena()
        self.assertEqual(login_mod.entry_pass.cget("show"), "*", "Al pulsar de nuevo debe volver a asterisco")
        self.assertIn("Mostrar contraseña", login_mod.lbl_toggle_pass.cget("text"))
        self.assertEqual(login_mod.pass_var.get(), "MiClaveSuperSegura2026!", "El texto no debe cambiar al ocultar")

        # Limpiar campos restaura estado oculto
        login_mod.limpiar_campos()
        self.assertEqual(login_mod.pass_var.get(), "")
        self.assertEqual(login_mod.entry_pass.cget("show"), "*")
        self.assertIn("Mostrar contraseña", login_mod.lbl_toggle_pass.cget("text"))

    def test_02_validacion_credenciales_correctas_e_incorrectas(self):
        """Prueba A: Validación de credenciales para login sin logging de contraseñas."""
        datos = obtener_usuario_por_credenciales("admin_test_flow", "AdminPassword123#")
        self.assertIsNotNone(datos, "Las credenciales correctas deben retornar el perfil de usuario")
        self.assertIsInstance(datos, dict)
        self.assertIn(datos.get("rol", "").lower(), ("administrador", "admin"))

        datos_err = obtener_usuario_por_credenciales("admin_test_flow", "PasswordErronea999#")
        self.assertIsNone(datos_err, "Las credenciales incorrectas deben retornar None")

    def test_03_pantalla_carga_con_callback_y_sin_deadlock(self):
        """Prueba B: La pantalla de carga ejecuta animaciones y llama a on_complete sin congelar el hilo."""
        callback_ejecutado = False

        def _al_completar():
            nonlocal callback_ejecutado
            callback_ejecutado = True

        datos_u = {'nombre': 'Eduardo', 'usuario': 'eduardo', 'rol': 'Administrador'}
        t0 = time.time()
        win_carga = mostrar_carga("Eduardo", datos_u, parent=login_mod.ventana, on_complete=_al_completar)
        self.assertIsNotNone(win_carga)

        # Usar wait_window para bombear el event loop hasta que la pantalla de carga complete su animación
        try:
            login_mod.ventana.wait_window(win_carga)
        except Exception:
            pass

        duracion = time.time() - t0
        self.assertTrue(callback_ejecutado, "El callback on_complete debió ejecutarse al terminar la pantalla de carga")
        self.assertLess(duracion, 4.0, "La pantalla de carga no debe tardar más de 4s")

    def test_04_arranque_dashboard_completo_y_visibilidad(self):
        """Prueba B: Inicio de sesión completo abre el dashboard, lo hace visible y activo."""
        mock_user_data = {
            'id': 1,
            'nombre': 'Eduardo Admin',
            'usuario': 'admin_test_flow',
            'rol': 'Administrador',
            'permisos': 'admin'
        }

        dashboard = iniciar_dashboard("admin_test_flow", mock_user_data, login_window=login_mod.ventana)
        self.assertIsNotNone(dashboard, "iniciar_dashboard debe retornar la instancia VmPOSDashboard")
        self.assertTrue(dashboard.winfo_exists(), "La ventana del dashboard debe existir")
        
        # Comprobar visibilidad y estado normal (no iconic/minimizado)
        self.assertEqual(dashboard.state(), "normal")
        login_mod.ventana.update_idletasks()

        # Repetición: simular cierre y reapertura
        dashboard.destroy()
        login_mod.ventana.update_idletasks()

        dashboard2 = iniciar_dashboard("admin_test_flow", mock_user_data, login_window=login_mod.ventana)
        self.assertIsNotNone(dashboard2)
        self.assertTrue(dashboard2.winfo_exists())
        self.assertEqual(dashboard2.state(), "normal")

        dashboard2.destroy()
        login_mod.ventana.update_idletasks()

    def test_05_roles_administrador_vendedor_operario(self):
        """Prueba C: Los 3 roles llegan al menú correspondiente con sus permisos específicos."""
        # 1. Administrador
        data_admin = {'id': 1, 'usuario': 'admin_user', 'rol': 'Administrador'}
        dash_admin = iniciar_dashboard("admin_user", data_admin, login_window=login_mod.ventana)
        self.assertEqual(dash_admin.rol_usuario, "administrador")
        self.assertEqual(dash_admin.permisos.get("Inventario"), 1)
        self.assertEqual(dash_admin.permisos.get("Usuarios"), 1)
        self.assertEqual(dash_admin.permisos.get("Contabilidad"), 1)
        self.assertEqual(dash_admin.permisos.get("Nómina"), 1)
        dash_admin.destroy()
        login_mod.ventana.update_idletasks()

        # 2. Vendedor
        data_vend = {'id': 2, 'usuario': 'vendedor_user', 'rol': 'Vendedor'}
        dash_vend = iniciar_dashboard("vendedor_user", data_vend, login_window=login_mod.ventana)
        self.assertEqual(dash_vend.rol_usuario, "vendedor")
        self.assertEqual(dash_vend.permisos.get("Ventas"), 1)
        self.assertEqual(dash_vend.permisos.get("Caja"), 1)
        self.assertEqual(dash_vend.permisos.get("Inventario"), 0)
        self.assertEqual(dash_vend.permisos.get("Usuarios"), 0)
        dash_vend.destroy()
        login_mod.ventana.update_idletasks()

        # 3. Operario
        data_oper = {'id': 3, 'usuario': 'operario_user', 'rol': 'Operario'}
        dash_oper = iniciar_dashboard("operario_user", data_oper, login_window=login_mod.ventana)
        self.assertEqual(dash_oper.rol_usuario, "operario")
        self.assertEqual(dash_oper.permisos.get("Ventas"), 1)
        self.assertEqual(dash_oper.permisos.get("Turnos"), 1)
        self.assertEqual(dash_oper.permisos.get("Inventario"), 0)
        dash_oper.destroy()
        login_mod.ventana.update_idletasks()

    def test_06_regresion_modulos_esenciales_dashboard(self):
        """Prueba D: Verificación de no regresión en los módulos funcionales del Dashboard."""
        data_admin = {'id': 1, 'usuario': 'admin_check', 'rol': 'Administrador'}
        dash = iniciar_dashboard("admin_check", data_admin, login_window=login_mod.ventana)
        
        # Verificar métodos de apertura de módulos intactos
        modulos_verificar = [
            "_abrir_ventas",
            "_abrir_inventario",
            "_abrir_caja",
            "_abrir_contabilidad",
            "_abrir_clientes",
            "_abrir_usuarios",
            "_abrir_nomina",
            "_abrir_turnos",
            "_abrir_gestion_ventas",
            "_abrir_configuracion",
            "_abrir_control_gastos",
            "_abrir_generador_codigo_barras",
            "_cerrar_sesion",
            "_salir_sistema"
        ]
        for mod in modulos_verificar:
            self.assertTrue(hasattr(dash, mod), f"El dashboard debe contener el método {mod}")
            self.assertTrue(callable(getattr(dash, mod)), f"El método {mod} debe ser ejecutable")

        dash.destroy()
        login_mod.ventana.update_idletasks()


if __name__ == "__main__":
    unittest.main()
