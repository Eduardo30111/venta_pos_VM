#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests automatizados para la Pantalla de Carga y Bienvenida por Voz en VmPOS.
Archivo: tests/test_pantalla_carga_y_bienvenida.py
"""

import unittest
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from interface.pantalla_carga import (
    generar_saludo_bienvenida,
    reproducir_bienvenida_asincrona,
    mostrar_carga
)

class TestPantallaCargaYBienvenida(unittest.TestCase):

    def test_01_generacion_saludo_dinamico(self):
        """Verifica que el saludo respete nombres y concordancia de género adecuadamente."""
        casos = [
            ("Eduardo", "Bienvenido, Eduardo"),
            ("Carlos", "Bienvenido, Carlos"),
            ("Andrés", "Bienvenido, Andrés"),
            ("Marcela", "Bienvenida, Marcela"),
            ("María", "Bienvenida, María"),
            ("Ana", "Bienvenida, Ana"),
            ("Admin", "Bienvenido, Admin"),
            ("Pedro", "Bienvenido, Pedro"),
            ("Luis", "Bienvenido, Luis"),
            ("", "Bienvenido"),
            (None, "Bienvenido")
        ]
        for entrada, esperado in casos:
            with self.subTest(nombre=entrada):
                resultado = generar_saludo_bienvenida(entrada)
                self.assertEqual(resultado, esperado)

    def test_02_reproduccion_asincrona_no_bloqueante(self):
        """Verifica que la bienvenida por voz no bloquee el hilo principal."""
        t_inicio = time.time()
        # Se debe ejecutar de inmediato retornando el control sin esperar al sintetizador
        reproducir_bienvenida_asincrona("Eduardo", forzar=True)
        duracion = time.time() - t_inicio
        self.assertLess(duracion, 0.5, "La función de voz bloqueó el hilo principal más de 500ms")

    def test_03_deduplicacion_reproduccion_sesion(self):
        """Verifica que no se duplique la reproducción para la misma sesión."""
        import interface.pantalla_carga as pc
        pc._ULTIMA_VOZ_REPRODUCIDA = None
        
        # Primera llamada debe registrar la sesión
        reproducir_bienvenida_asincrona("Carlos", forzar=False)
        primera_clave = pc._ULTIMA_VOZ_REPRODUCIDA
        self.assertIsNotNone(primera_clave)
        
        # Segunda llamada con los mismos datos no debe alterar el estado
        reproducir_bienvenida_asincrona("Carlos", forzar=False)
        self.assertEqual(pc._ULTIMA_VOZ_REPRODUCIDA, primera_clave)

    def test_04_pantalla_carga_ciclo_completo(self):
        """Verifica que mostrar_carga cree y destruya la ventana limpiamente."""
        datos_test = {
            'nombre': 'Eduardo',
            'usuario': 'eduardo',
            'rol': 'Administrador',
            'rol_completo': 'Administrador'
        }
        # Ejecuta la pantalla de carga (se auto-cierra tras completar la animación)
        t_inicio = time.time()
        ventana = mostrar_carga("Eduardo", datos_test)
        duracion = time.time() - t_inicio
        
        self.assertIsNotNone(ventana)
        # La animación dura ~1.2s a 1.5s
        self.assertLess(duracion, 4.0, "La pantalla de carga tardó más de 4s en cerrarse")

    def test_05_integracion_inicio_sesion(self):
        """Verifica que interface/inicio_sesion.py contenga la llamada a mostrar_carga."""
        ruta_inicio = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "interface", "inicio_sesion.py")
        with open(ruta_inicio, "r", encoding="utf-8") as f:
            contenido = f.read()
        self.assertIn("mostrar_carga", contenido)
        self.assertIn("iniciar_dashboard", contenido)

if __name__ == "__main__":
    unittest.main()
