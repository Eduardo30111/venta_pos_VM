import unittest
import sqlite3
import os
from interface.proveedores_manager import recalcular_saldo_proveedor, _sincronizar_liquidacion_local_sqlite


class TestProveedorPhantomBalance(unittest.TestCase):
    def setUp(self):
        self.db_path = "database/test_proveedor_balance.db"
        if os.path.exists(self.db_path):
            os.remove(self.db_path)
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT,
                documento_nit TEXT,
                saldo_acumulado REAL DEFAULT 0.0,
                total_ventas REAL DEFAULT 0.0,
                total_comisiones REAL DEFAULT 0.0,
                total_pagado REAL DEFAULT 0.0,
                estado TEXT DEFAULT 'Activo'
            );
        """)
        cur.execute("""
            CREATE TABLE liquidaciones_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_recibo TEXT UNIQUE,
                proveedor_id INTEGER,
                proveedor_nombre TEXT,
                monto_liquidado REAL,
                saldo_anterior REAL,
                saldo_restante REAL,
                tipo_pago TEXT,
                metodo_pago TEXT,
                referencia TEXT,
                fecha TEXT,
                hora TEXT,
                mes_anio TEXT,
                usuario TEXT,
                observaciones TEXT,
                estado TEXT
            );
        """)
        cur.execute("""
            CREATE TABLE cuentas_por_pagar_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proveedor_id INTEGER,
                proveedor_nombre TEXT,
                monto_por_pagar REAL,
                monto_pagado REAL DEFAULT 0.0,
                saldo_pendiente REAL,
                estado TEXT DEFAULT 'Pendiente'
            );
        """)
        # Insert provider with initial 6300 debt
        cur.execute("INSERT INTO proveedores (id, nombre, saldo_acumulado, total_ventas, total_comisiones, total_pagado) VALUES (10, 'Proveedor Prueba Saldo', 6300.0, 6300.0, 6300.0, 0.0)")
        cur.execute("INSERT INTO cuentas_por_pagar_proveedores (proveedor_id, proveedor_nombre, monto_por_pagar, monto_pagado, saldo_pendiente, estado) VALUES (10, 'Proveedor Prueba Saldo', 6300.0, 0.0, 6300.0, 'Pendiente')")
        conn.commit()
        conn.close()

    def tearDown(self):
        if os.path.exists(self.db_path):
            try:
                os.remove(self.db_path)
            except Exception:
                pass

    def test_liquidacion_pone_saldo_en_cero_sin_resurreccion(self):
        # 1. Liquidar totalmente al proveedor en SQLite local
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        _sincronizar_liquidacion_local_sqlite(
            cur=cur,
            proveedor_id=10,
            monto_flt=6300.0,
            metodo_pago="Efectivo",
            referencia="REF-6300",
            usuario="admin",
            observaciones="Liquidación total",
            numero_recibo="REC-00010"
        )
        conn.commit()

        # 2. Verificar que el saldo_acumulado es 0.0 y cuentas_por_pagar está Pagada
        cur.execute("SELECT saldo_acumulado, total_pagado FROM proveedores WHERE id = 10")
        row_p = cur.fetchone()
        cur.execute("SELECT saldo_pendiente, estado FROM cuentas_por_pagar_proveedores WHERE proveedor_id = 10")
        row_cxp = cur.fetchone()
        conn.close()

        self.assertEqual(row_p[0], 0.0, f"Saldo acumulado debió ser 0.0 pero fue {row_p[0]}")
        self.assertEqual(row_p[1], 6300.0, f"Total pagado debió ser 6300.0 pero fue {row_p[1]}")
        self.assertEqual(row_cxp[0], 0.0, f"Saldo pendiente debió ser 0.0 pero fue {row_cxp[0]}")
        self.assertEqual(row_cxp[1], "Pagada", f"Estado debió ser 'Pagada' pero fue {row_cxp[1]}")


if __name__ == "__main__":
    unittest.main()
