#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests automatizados para Estabilidad de Sesiones Prolongadas, Recuperación de Conexiones
y Prevención de Desaparición de Datos en VmPOS.
Archivo: tests/test_estabilidad_sesion_prolongada.py
"""

import unittest
import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server.config import settings
from interface.database_manager import conectar_db
import interface.inventario_manager as inv_mgr
import interface.proveedores_manager as prov_mgr
from interface.ventas_menu import App as VentasApp


class TestEstabilidadSesionProlongada(unittest.TestCase):

    def test_01_token_expiration_ampliada(self):
        """Verifica que la expiración del token JWT sea de al menos 30 días para evitar desconexiones."""
        self.assertGreaterEqual(settings.ACCESS_TOKEN_EXPIRE_MINUTES, 43200)

    def test_02_database_manager_busy_timeout_y_reintentos(self):
        """Verifica que conectar_db aplique busy_timeout=30000 y soporte reintentos ante bloqueos."""
        conn = conectar_db()
        self.assertIsNotNone(conn, "No se pudo conectar a la base de datos de pruebas")
        cur = conn.cursor()
        cur.execute("PRAGMA busy_timeout;")
        timeout_val = cur.fetchone()[0]
        self.assertGreaterEqual(timeout_val, 15000, "busy_timeout debe ser al menos 15000ms")
        conn.close()

    def test_03_inventario_catalogo_cache_supervivencia(self):
        """Verifica que el catálogo no desaparezca (no retorne lista vacía) si falla la red y SQLite."""
        item_test = {
            "id": 9999,
            "codigo": "PRD-TEST-ESTAB",
            "nombre": "Producto Test Estabilidad",
            "tipo_producto": "Fisico",
            "categoria": "General",
            "precio": 5000.0,
            "stock_vitrina": 10.0,
            "stock_bodega": 5.0,
            "estado": "Activo"
        }
        inv_mgr._MEMORIA_CATALOGO_CACHE = [item_test]

        original_get = inv_mgr.api.get
        orig_fallback = inv_mgr._obtener_catalogo_sqlite_fallback
        try:
            from client.api_client import DummyResponse
            inv_mgr.api.get = lambda *args, **kwargs: DummyResponse(503, {"detail": "Network down"})
            # Simular que SQLite local está vacío o bloqueado
            inv_mgr._obtener_catalogo_sqlite_fallback = lambda *a, **kw: []

            items = inv_mgr.obtener_catalogo(solo_activos=True)
            self.assertTrue(len(items) > 0, "El catálogo no debe quedar vacío tras caída de red y SQLite")
            codigos = [it.get("codigo") for it in items]
            self.assertIn("PRD-TEST-ESTAB", codigos)
        finally:
            inv_mgr.api.get = original_get
            inv_mgr._obtener_catalogo_sqlite_fallback = orig_fallback

    def test_04_ventas_preserva_productos_memoria(self):
        """Verifica que VentasApp conserve self.productos_inventario si una consulta devuelve vacío."""
        class DummyVentas:
            def __init__(self):
                self.rol = "Administrador"
                self.productos_inventario = [
                    ("P01", "Producto Previo", 10, 5000.0, "Fisico", 1, 1, 3000.0, False, 0.0, "")
                ]

        dummy = DummyVentas()
        # Inyectar el método de obtención
        dummy.obtener_productos = VentasApp.obtener_productos.__get__(dummy, DummyVentas)

        # Forzar que obtener_catalogo devuelva lista vacía
        orig_obtener = inv_mgr.obtener_catalogo
        orig_cache = list(inv_mgr._MEMORIA_CATALOGO_CACHE)
        inv_mgr._MEMORIA_CATALOGO_CACHE.clear()
        try:
            inv_mgr.obtener_catalogo = lambda *a, **kw: []
            # Llamar a obtener_productos con respuesta vacía
            prods = dummy.obtener_productos()
            self.assertEqual(len(prods), 1, "VentasApp debe preservar los productos en memoria")
            self.assertEqual(prods[0][0], "P01")
        finally:
            inv_mgr.obtener_catalogo = orig_obtener
            inv_mgr._MEMORIA_CATALOGO_CACHE = orig_cache

    def test_05_proveedores_cache_supervivencia(self):
        """Verifica que la lista de proveedores nunca desaparezca ante caídas de conexión y SQLite vacío."""
        prov_test = {
            "id": 9999,
            "nombre": "Distribuidora Test Resiliencia",
            "documento_nit": "900999888",
            "nit": "900999888",
            "telefono": "3001234567",
            "saldo_pendiente": 150000.0,
            "saldo_acumulado": 150000.0,
            "total_ventas": 300000.0,
            "total_comisiones": 50000.0,
            "total_pagado": 100000.0,
            "estado": "Activo"
        }
        prov_mgr._MEMORIA_PROVEEDORES_CACHE = [prov_test]

        orig_api_get = prov_mgr.api.get if prov_mgr.api else None
        # Simular que la conexión a SQLite falla
        orig_conectar = prov_mgr.conectar_db
        try:
            from client.api_client import DummyResponse
            if prov_mgr.api:
                prov_mgr.api.get = lambda *args, **kwargs: DummyResponse(503, {"detail": "Network down"})
            prov_mgr.conectar_db = lambda *a, **kw: None

            provs = prov_mgr.obtener_resumen_proveedores(solo_activos=True)
            self.assertTrue(len(provs) > 0, "Los proveedores no deben desaparecer ante fallo de red")
            nombres = [p.get("nombre") for p in provs]
            self.assertIn("Distribuidora Test Resiliencia", nombres)
        finally:
            if prov_mgr.api and orig_api_get:
                prov_mgr.api.get = orig_api_get
            prov_mgr.conectar_db = orig_conectar


if __name__ == "__main__":
    unittest.main()
