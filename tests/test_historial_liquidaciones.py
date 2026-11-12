"""
Pruebas unitarias para el Historial Permanente de Liquidaciones y Pagos:
1. Nómina: Filtro por fecha específica, rango de fechas, mes y todas las fechas.
2. Proveedores: Filtro por fecha específica, rango de fechas, mes y todas las fechas.
3. Liquidación de proveedor sin error "Proveedor con ID 1 no encontrado":
   - Autocuración si el proveedor existe en cuentas_por_pagar_proveedores.
   - Sincronización adecuada y registro contable inmutable.
"""

import unittest
import sqlite3
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from interface.proveedores_manager import (
    obtener_historial_liquidaciones_proveedor,
    liquidar_proveedor_db,
)
from interface.nomina_manager import (
    obtener_historial_pagos_nomina,
)


class TestHistorialLiquidaciones(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        cur = self.conn.cursor()

        # Tabla de proveedores y liquidaciones
        cur.execute("""
            CREATE TABLE IF NOT EXISTS proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                nit TEXT,
                telefono TEXT,
                saldo_acumulado REAL DEFAULT 0.0,
                estado TEXT DEFAULT 'Activo'
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS liquidaciones_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_recibo TEXT,
                proveedor_id INTEGER NOT NULL,
                proveedor_nombre TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT DEFAULT '12:00:00',
                mes_anio TEXT NOT NULL,
                monto_liquidado REAL NOT NULL,
                saldo_anterior REAL DEFAULT 0.0,
                saldo_restante REAL DEFAULT 0.0,
                tipo_pago TEXT DEFAULT 'Total',
                metodo_pago TEXT NOT NULL,
                referencia TEXT,
                observaciones TEXT,
                usuario TEXT NOT NULL,
                estado TEXT DEFAULT 'Aplicada',
                sesion_caja_id INTEGER
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS cuentas_por_pagar_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proveedor_id INTEGER NOT NULL,
                proveedor_nombre TEXT NOT NULL,
                id_venta INTEGER DEFAULT 0,
                codigo_servicio TEXT DEFAULT '',
                nombre_servicio TEXT DEFAULT '',
                precio_venta REAL DEFAULT 0.0,
                porcentaje_comision REAL DEFAULT 0.0,
                monto_comision REAL DEFAULT 0.0,
                monto_por_pagar REAL NOT NULL,
                monto_pagado REAL NOT NULL DEFAULT 0.0,
                saldo_pendiente REAL NOT NULL,
                estado TEXT DEFAULT 'Pendiente',
                fecha TEXT NOT NULL,
                hora TEXT DEFAULT '12:00:00',
                usuario TEXT DEFAULT 'Administrador'
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT,
                categoria TEXT,
                descripcion TEXT,
                monto REAL,
                metodo_pago TEXT,
                fecha TEXT,
                hora TEXT,
                usuario TEXT,
                comprobante TEXT,
                proveedor_id INTEGER,
                proveedor_nombre TEXT,
                sesion_caja_id INTEGER
            );
        """)
        # Tabla de nómina pagos y usuarios
        cur.execute("""
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                apellidos TEXT,
                usuario TEXT NOT NULL,
                rol TEXT DEFAULT 'Vendedor'
            );
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS nomina_pagos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER NOT NULL,
                usuario_nombre TEXT,
                rol TEXT,
                fecha_pago TEXT NOT NULL,
                hora_pago TEXT DEFAULT '12:00:00',
                periodo TEXT,
                tipo_operacion TEXT DEFAULT 'LIQUIDACION_TOTAL',
                monto_pagado REAL NOT NULL,
                metodo_pago TEXT NOT NULL DEFAULT 'Efectivo',
                referencia TEXT,
                saldo_pendiente_despues REAL DEFAULT 0.0,
                estado TEXT DEFAULT 'Aplicado'
            );
        """)

        # Insertar datos de prueba para liquidaciones_proveedores
        cur.execute("""
            INSERT INTO liquidaciones_proveedores 
            (numero_recibo, proveedor_id, proveedor_nombre, fecha, mes_anio, monto_liquidado, metodo_pago, referencia, usuario)
            VALUES 
            ('LP-0001', 1, 'Distribuidora Central', '2026-11-01 10:00:00', '2026-11', 50000.0, 'Efectivo', 'REF-01', 'Admin'),
            ('LP-0002', 1, 'Distribuidora Central', '2026-11-05 14:30:00', '2026-11', 30000.0, 'Transferencia', 'NEQUI-99', 'Admin'),
            ('LP-0003', 2, 'Papelería La Gran Vía', '2026-10-15 09:15:00', '2026-10', 120000.0, 'Efectivo', 'REF-02', 'Cajero')
        """)

        # Insertar datos de prueba para nomina_pagos
        cur.execute("""
            INSERT INTO usuarios (id, nombre, apellidos, usuario, rol)
            VALUES
            (101, 'Carlos', 'Perez', 'cperez', 'Vendedor'),
            (102, 'Ana', 'Gomez', 'agomez', 'Administrador')
        """)
        cur.execute("""
            INSERT INTO nomina_pagos
            (usuario_id, usuario_nombre, rol, fecha_pago, monto_pagado, metodo_pago, referencia)
            VALUES
            (101, 'Carlos Perez', 'Vendedor', '2026-11-02 11:00:00', 550000.0, 'Transferencia', 'NOM-01'),
            (102, 'Ana Gomez', 'Administrador', '2026-11-08 17:00:00', 450000.0, 'Efectivo', 'NOM-02'),
            (101, 'Carlos Perez', 'Vendedor', '2026-10-31 18:00:00', 550000.0, 'Transferencia', 'NOM-03')
        """)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_filtro_proveedores_todas_las_fechas(self):
        """Sin filtros debe retornar las 3 liquidaciones de proveedores."""
        items = obtener_historial_liquidaciones_proveedor(conn=self.conn)
        self.assertEqual(len(items), 3)

    def test_filtro_proveedores_fecha_especifica(self):
        """Filtrar por '2026-11-01' debe retornar exactamente 1 registro."""
        items = obtener_historial_liquidaciones_proveedor(fecha_especifica="2026-11-01", conn=self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["numero_recibo"], "LP-0001")

    def test_filtro_proveedores_rango_fechas(self):
        """Filtrar rango 2026-11-01 a 2026-11-10 debe retornar 2 registros."""
        items = obtener_historial_liquidaciones_proveedor(fecha_inicio="2026-11-01", fecha_fin="2026-11-10", conn=self.conn)
        self.assertEqual(len(items), 2)

    def test_filtro_proveedores_por_mes(self):
        """Filtrar por '2026-10' debe retornar 1 registro."""
        items = obtener_historial_liquidaciones_proveedor(mes_anio="2026-10", conn=self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["proveedor_nombre"], "Papelería La Gran Vía")

    def test_filtro_nomina_rango_fechas(self):
        """Filtrar nómina entre 2026-11-01 y 2026-11-05 debe retornar 1 registro."""
        items = obtener_historial_pagos_nomina(fecha_inicio="2026-11-01", fecha_fin="2026-11-05", conn=self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["usuario_nombre"], "Carlos Perez")

    def test_liquidar_proveedor_autocuracion_id(self):
        """
        Si un proveedor existe en cuentas_por_pagar_proveedores pero no en la tabla proveedores,
        liquidar_proveedor_db debe autocurarlo en vez de fallar con 'Proveedor con ID 1 no encontrado'.
        """
        cur = self.conn.cursor()
        cur.execute("""
            INSERT INTO cuentas_por_pagar_proveedores (proveedor_id, proveedor_nombre, fecha, precio_venta, monto_por_pagar, saldo_pendiente)
            VALUES (99, 'Proveedor Especial 99', '2026-11-10', 40000.0, 40000.0, 40000.0)
        """)
        self.conn.commit()

        # Liquidar sin que esté previamente en la tabla 'proveedores'
        res = liquidar_proveedor_db(
            proveedor_id=99,
            monto=40000.0,
            metodo_pago="Efectivo",
            referencia="ABONO-99",
            usuario="Admin",
            conn=self.conn
        )
        self.assertTrue(res.get("exito"), f"Fallo al liquidar: {res.get('mensaje')}")
        self.assertEqual(res.get("monto_liquidado"), 40000.0)

        # Verificar que se insertó el registro de liquidación
        items = obtener_historial_liquidaciones_proveedor(proveedor_id=99, conn=self.conn)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["monto_pagado"], 40000.0)


if __name__ == "__main__":
    unittest.main()
