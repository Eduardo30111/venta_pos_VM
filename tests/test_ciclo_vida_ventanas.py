#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests automatizados para Control de Instancia Única, Restauración de Ventanas Minimizadas
y Liberación de Recursos / Grabs en VmPOS.
Archivo: tests/test_ciclo_vida_ventanas.py
"""

import unittest
import os
import sys
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.session_manager import session_mgr


class TestCicloVidaVentanas(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Crear root oculto para pruebas de widgets Tkinter
        cls.root = tk.Tk()
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.root.destroy()
        except Exception:
            pass

    def setUp(self):
        session_mgr._modulos.clear()
        session_mgr._ventanas.clear()

    def test_01_registro_y_deteccion_instancia_unica(self):
        """Verifica que registrar un módulo permita detectarlo e impida aperturas duplicadas."""
        top = tk.Toplevel(self.root)
        top.title("Módulo Ventas Test")
        session_mgr.registrar_modulo("ventas", top)

        # La consulta debe indicar que el módulo ya existe
        self.assertTrue(session_mgr.enfocar_o_restaurar_modulo("ventas"))
        w = session_mgr.obtener_modulo("ventas")
        self.assertEqual(w, top)

        # Si el módulo no existe, debe retornar False
        self.assertFalse(session_mgr.enfocar_o_restaurar_modulo("inventario"))
        top.destroy()

    def test_02_restauracion_ventana_minimizada(self):
        """Verifica que enfocar_o_restaurar_modulo devuelva la ventana de 'iconic' a 'normal'."""
        top = tk.Toplevel(self.root)
        top.title("Módulo Inventario Test")
        session_mgr.registrar_modulo("inventario", top)

        # Minimizar ventana
        try:
            top.iconify()
        except Exception:
            pass

        # Restaurar
        ok = session_mgr.enfocar_o_restaurar_modulo("inventario")
        self.assertTrue(ok)
        self.assertEqual(top.state(), "normal", "La ventana debe volver a estado normal tras restaurar")
        top.destroy()

    def test_03_liberacion_grabs_y_destruccion_segura(self):
        """Verifica que cerrar_todas_las_ventanas y liberar_todos_los_grabs eviten bloqueos."""
        modal = tk.Toplevel(self.root)
        modal.title("Modal Dialog Test")
        session_mgr.registrar_ventana(modal)

        # Aplicar grab_set
        try:
            modal.grab_set()
        except Exception:
            pass

        # Liberar grabs
        session_mgr.liberar_todos_los_grabs()
        # Cerrar todas las ventanas
        session_mgr.cerrar_todas_las_ventanas()
        self.assertEqual(len(session_mgr._ventanas), 0)
        self.assertEqual(len(session_mgr._modulos), 0)

    def test_04_desregistro_automatico_al_destruir(self):
        """Verifica que al destruirse un widget, obtener_modulo no devuelva referencias muertas."""
        top = tk.Toplevel(self.root)
        session_mgr.registrar_modulo("caja", top)
        self.assertIsNotNone(session_mgr.obtener_modulo("caja"))

        # Destruir ventana
        top.destroy()
        # Al volver a consultar, debe detectar que ya no existe y retornar None
        self.assertIsNone(session_mgr.obtener_modulo("caja"))
        self.assertFalse(session_mgr.enfocar_o_restaurar_modulo("caja"))

    def test_05_cancelacion_segura_de_timers(self):
        """Verifica que registrar y cancelar timers funcione limpiamente sin excepciones."""
        ejecutado = [False]
        def _cb():
            ejecutado[0] = True

        aid = self.root.after(500, _cb)
        session_mgr.registrar_timer(self.root, aid)
        self.assertTrue(len(session_mgr._timers) > 0)

        # Cancelar timers antes de ejecución
        session_mgr.cancelar_timers(self.root)
        self.assertEqual(len(session_mgr._timers), 0)


if __name__ == "__main__":
    unittest.main()
