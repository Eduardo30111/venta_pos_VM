#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: database_manager.py
Manejador centralizado de la base de datos de VmPOS.
Reemplaza todas las definiciones locales de bases de datos para evitar inconsistencias.
"""

import sqlite3
import os
import sys

# Importar rutas de config.py
try:
    from interface.config import DB_VENTAS_PATH, DB_USUARIOS_PATH
except ImportError:
    try:
        from config import DB_VENTAS_PATH, DB_USUARIOS_PATH
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from config import DB_VENTAS_PATH, DB_USUARIOS_PATH

def conectar_db(db_path=None):
    """
    Establece conexión con la base de datos especificada.
    Por defecto conecta a ventas.db o a la ruta configurada en VMPOS_DB_VENTAS.
    """
    if db_path is None:
        db_path = os.environ.get("VMPOS_DB_VENTAS") or DB_VENTAS_PATH
    try:
        conn = sqlite3.connect(db_path)
        return conn
    except Exception as e:
        print(f"Error conectando a la base de datos {db_path}: {e}")
        return None

def inicializar_base_datos(db_path=None):
    """
    Crea o verifica que todas las tablas de la base de datos de ventas.db existan
    con el esquema correcto y unificado.
    """
    if db_path is None:
        db_path = os.environ.get("VMPOS_DB_VENTAS") or DB_VENTAS_PATH
    conn = conectar_db(db_path)
    if not conn:
        print("❌ Error al inicializar base de datos: No se pudo conectar.")
        return False
        
    try:
        cursor = conn.cursor()
        
        # 1. Tabla de Productos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS productos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                precio REAL NOT NULL,
                costo REAL DEFAULT 0,
                stock INTEGER DEFAULT 0
            )
        """)
        
        # 2. Tabla de Ventas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ventas (
                id_venta INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_venta TEXT NOT NULL,
                hora_venta TEXT NOT NULL,
                documento_cliente TEXT NOT NULL,
                total_venta REAL NOT NULL
            )
        """)
        
        # 3. Tabla de Detalle Ventas
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS detalle_ventas (
                id_detalle INTEGER PRIMARY KEY AUTOINCREMENT,
                id_venta INTEGER NOT NULL,
                codigo_producto TEXT NOT NULL,
                nombre_producto TEXT NOT NULL,
                precio_unitario REAL NOT NULL,
                cantidad INTEGER NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (id_venta) REFERENCES ventas (id_venta)
            )
        """)
        
        # 4. Tabla de Clientes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cedula TEXT UNIQUE NOT NULL,
                nombre TEXT NOT NULL,
                email TEXT,
                telefono TEXT,
                fecha_registro TEXT NOT NULL
            )
        """)
        
        # 5. Tabla de Gastos
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gastos (
                id_gasto INTEGER PRIMARY KEY AUTOINCREMENT,
                concepto TEXT NOT NULL,
                valor REAL NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 6. Tabla de Reportes
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reportes (
                id_reporte INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,
                fecha_inicio TEXT NOT NULL,
                fecha_fin TEXT NOT NULL,
                resumen TEXT,
                ruta_pdf TEXT
            )
        """)

        # 7. Tabla de Proveedores
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nombre TEXT NOT NULL,
                telefono TEXT,
                saldo_acumulado REAL DEFAULT 0.0
            )
        """)

        # 8. Tabla de Historial de Liquidaciones (Nómina)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS historial_liquidaciones (
                id_liquidacion INTEGER PRIMARY KEY AUTOINCREMENT,
                tipo TEXT NOT NULL,          -- 'Empleado' o 'Proveedor'
                persona_id INTEGER NOT NULL, -- ID del usuario o del proveedor
                nombre_persona TEXT NOT NULL,
                monto REAL NOT NULL,
                fecha TEXT NOT NULL,
                mes_anio TEXT NOT NULL
            )
        """)

        # 9. Tabla de Sesiones de Caja (Turnos de Caja / Arqueo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sesiones_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha_apertura TEXT NOT NULL,
                hora_apertura TEXT NOT NULL,
                usuario_apertura TEXT NOT NULL,
                monto_inicial REAL NOT NULL DEFAULT 0.0,
                estado TEXT NOT NULL DEFAULT 'Abierta',
                fecha_cierre TEXT,
                hora_cierre TEXT,
                usuario_cierre TEXT,
                monto_esperado_efectivo REAL DEFAULT 0.0,
                monto_real_contado REAL DEFAULT 0.0,
                diferencia REAL DEFAULT 0.0,
                observaciones TEXT
            )
        """)

        # 10. Tabla de Movimientos de Caja (Libro Mayor de Efectivo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_caja (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sesion_caja_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                tipo TEXT NOT NULL, -- 'APERTURA', 'VENTA_EFECTIVO', 'ABONO_EFECTIVO', 'EGRESO', 'RETIRO', 'AJUSTE', 'DEVOLUCION_VENTA', 'CIERRE'
                monto REAL NOT NULL,
                usuario TEXT NOT NULL,
                terminal TEXT DEFAULT 'Terminal-1',
                referencia_id TEXT,
                descripcion TEXT,
                FOREIGN KEY (sesion_caja_id) REFERENCES sesiones_caja (id)
            )
        """)

        # 11. Tabla de Auditoría de Ventas (Trazabilidad 100% de Ediciones y Anulaciones)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS auditoria_ventas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_venta INTEGER NOT NULL,
                numero_venta TEXT,
                accion TEXT NOT NULL, -- 'CREACION', 'MODIFICACION', 'ANULACION'
                usuario TEXT NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                terminal TEXT DEFAULT 'Terminal-1',
                motivo TEXT NOT NULL,
                valor_anterior REAL,
                valor_nuevo REAL,
                detalles_json TEXT,
                FOREIGN KEY (id_venta) REFERENCES ventas (id_venta)
            )
        """)

        conn.commit()

        # Migraciones (agregar columnas si no existen)
        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN metodo_pago TEXT DEFAULT 'Efectivo'")
        except sqlite3.OperationalError:
            pass # La columna ya existe

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN operario TEXT DEFAULT 'Administrador'")
        except sqlite3.OperationalError:
            pass

        # 12. Tabla de Gastos Recurrentes / Programados
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS gastos_recurrentes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concepto TEXT NOT NULL,
                categoria TEXT NOT NULL DEFAULT 'Fijo periódico',
                clasificacion TEXT NOT NULL DEFAULT 'Fijo periódico',
                descripcion TEXT DEFAULT '',
                valor REAL NOT NULL,
                frecuencia TEXT NOT NULL DEFAULT 'Mensual', -- 'Diaria', 'Semanal', 'Quincenal', 'Mensual', 'Anual'
                dia_corte INTEGER DEFAULT 1,
                proveedor TEXT DEFAULT '',
                metodo_pago_defecto TEXT DEFAULT 'Efectivo',
                activo INTEGER DEFAULT 1,
                ultimo_periodo_generado TEXT DEFAULT NULL,
                fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 13. Tabla de Pagos de Ventas (Múltiples medios de pago)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pagos_venta (
                id_pago INTEGER PRIMARY KEY AUTOINCREMENT,
                id_venta INTEGER NOT NULL,
                metodo_pago TEXT NOT NULL,
                monto REAL NOT NULL,
                referencia TEXT DEFAULT '',
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                FOREIGN KEY (id_venta) REFERENCES ventas (id_venta) ON DELETE CASCADE
            )
        """)

        # 14. Tabla Canónica de Movimientos Financieros (Libro Mayor Central Multicuenta)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_financieros (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                tipo TEXT NOT NULL,
                concepto TEXT NOT NULL,
                monto REAL NOT NULL,
                metodo_pago TEXT NOT NULL,
                cuenta_afectada TEXT NOT NULL,
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                referencia_origen TEXT DEFAULT '',
                sesion_caja_id INTEGER DEFAULT NULL,
                estado TEXT NOT NULL DEFAULT 'Activo',
                observaciones TEXT DEFAULT '',
                FOREIGN KEY (sesion_caja_id) REFERENCES sesiones_caja (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fin_fecha ON movimientos_financieros(fecha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fin_tipo ON movimientos_financieros(tipo)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fin_cuenta ON movimientos_financieros(cuenta_afectada)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fin_sesion ON movimientos_financieros(sesion_caja_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_mov_fin_ref ON movimientos_financieros(referencia_origen)")

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN estado TEXT DEFAULT 'Completada'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN motivo_anulacion TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN anulado_por TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN fecha_anulacion TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN modificado_por TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN fecha_modificacion TEXT")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE ventas ADD COLUMN sesion_caja_id INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE clientes ADD COLUMN permite_fiado INTEGER DEFAULT 0")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE clientes ADD COLUMN saldo_pendiente REAL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE productos ADD COLUMN tipo_producto TEXT DEFAULT 'Fisico'")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE productos ADD COLUMN descripcion TEXT DEFAULT ''")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE productos ADD COLUMN proveedor_id INTEGER DEFAULT NULL")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("ALTER TABLE gastos ADD COLUMN metodo_pago TEXT DEFAULT 'Efectivo'")
        except sqlite3.OperationalError:
            pass

        # Migraciones contables profesionales:
        # A. Costo histórico unitario en detalle_ventas
        try:
            cursor.execute("ALTER TABLE detalle_ventas ADD COLUMN costo_unitario REAL DEFAULT 0.0")
        except sqlite3.OperationalError:
            pass

        try:
            cursor.execute("""
                UPDATE detalle_ventas 
                SET costo_unitario = (
                    SELECT COALESCE(p.costo, 0.0) 
                    FROM productos p 
                    WHERE p.codigo = detalle_ventas.codigo_producto
                )
                WHERE costo_unitario IS NULL OR costo_unitario = 0.0
            """)
        except Exception:
            pass

        # B. Clasificación y estados contables en gastos
        for col_def in [
            "categoria TEXT DEFAULT 'Operativo diario'",
            "clasificacion TEXT DEFAULT 'Operativo diario'",
            "descripcion TEXT DEFAULT ''",
            "fecha_vencimiento TEXT DEFAULT NULL",
            "fecha_pago TEXT DEFAULT NULL",
            "frecuencia TEXT DEFAULT 'Único'",
            "estado TEXT DEFAULT 'Pagado'",
            "usuario TEXT DEFAULT 'Administrador'",
            "proveedor TEXT DEFAULT ''",
            "comprobante TEXT DEFAULT ''",
            "observaciones TEXT DEFAULT ''",
            "es_recurrente INTEGER DEFAULT 0",
            "recurrencia_id INTEGER DEFAULT NULL"
        ]:
            try:
                cursor.execute(f"ALTER TABLE gastos ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        try:
            cursor.execute("UPDATE gastos SET fecha_pago = fecha WHERE fecha_pago IS NULL AND estado = 'Pagado'")
        except Exception:
            pass

        # C. Conciliación bancaria en sesiones_caja
        for col_def in [
            "monto_transferencias_esperado REAL DEFAULT 0.0",
            "monto_transferencias_verificado REAL DEFAULT 0.0",
            "diferencia_banco REAL DEFAULT 0.0",
            "estado_banco TEXT DEFAULT 'Pendiente'"
        ]:
            try:
                cursor.execute(f"ALTER TABLE sesiones_caja ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # D. Inventario Profesional: Bodega, Vitrina, Categorías y Atributos en productos
        for col_def in [
            "stock_bodega REAL DEFAULT 0.0",
            "stock_vitrina REAL DEFAULT 0.0",
            "stock_minimo_bodega REAL DEFAULT 5.0",
            "stock_minimo_vitrina REAL DEFAULT 3.0",
            "categoria TEXT DEFAULT 'General'",
            "marca TEXT DEFAULT ''",
            "codigo_barras TEXT DEFAULT ''",
            "unidad_medida TEXT DEFAULT 'Unidad'",
            "estado TEXT DEFAULT 'Activo'",
            "fecha_creacion TEXT DEFAULT NULL",
            "fecha_modificacion TEXT DEFAULT NULL"
        ]:
            try:
                cursor.execute(f"ALTER TABLE productos ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # Migración inicial de existencias preexistentes a Bodega si ambas ubicaciones están en cero
        try:
            cursor.execute("""
                UPDATE productos 
                SET stock_bodega = stock 
                WHERE (stock_bodega IS NULL OR stock_bodega = 0.0) 
                  AND (stock_vitrina IS NULL OR stock_vitrina = 0.0) 
                  AND stock > 0
            """)
            cursor.execute("""
                UPDATE productos 
                SET stock = COALESCE(stock_bodega, 0.0) + COALESCE(stock_vitrina, 0.0)
            """)
        except Exception:
            pass

        # 15. Tabla de Movimientos de Inventario (Kárdex Inmutable)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS movimientos_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                producto_id INTEGER NOT NULL,
                codigo_producto TEXT NOT NULL,
                nombre_producto TEXT NOT NULL,
                tipo_movimiento TEXT NOT NULL, -- ENTRADA_COMPRA, TRASLADO_BODEGA_A_VITRINA, TRASLADO_VITRINA_A_BODEGA, VENTA, DEVOLUCION_VENTA, AJUSTE_POSITIVO, AJUSTE_NEGATIVO, CONSUMO_MATERIAL, ANULACION
                cantidad REAL NOT NULL,
                unidad_medida TEXT NOT NULL DEFAULT 'Unidad',
                ubicacion_origen TEXT NOT NULL,  -- BODEGA, VITRINA, PROVEEDOR, NINGUNA
                ubicacion_destino TEXT NOT NULL, -- VITRINA, BODEGA, CLIENTE, NINGUNA
                stock_origen_ant REAL DEFAULT 0.0,
                stock_origen_des REAL DEFAULT 0.0,
                stock_destino_ant REAL DEFAULT 0.0,
                stock_destino_des REAL DEFAULT 0.0,
                costo_unitario REAL DEFAULT 0.0,
                valor_total REAL DEFAULT 0.0,
                referencia TEXT DEFAULT '',     -- TR-00001, VENTA-12, CMP-00001, AJ-01
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                observaciones TEXT DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'Completado',
                FOREIGN KEY (producto_id) REFERENCES productos (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movinv_prod ON movimientos_inventario(codigo_producto)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movinv_fecha ON movimientos_inventario(fecha)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movinv_tipo ON movimientos_inventario(tipo_movimiento)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_movinv_ref ON movimientos_inventario(referencia)")

        # 16. Tabla de Traslados de Inventario
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS traslados_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_traslado TEXT UNIQUE NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                producto_id INTEGER NOT NULL,
                codigo_producto TEXT NOT NULL,
                nombre_producto TEXT NOT NULL,
                ubicacion_origen TEXT NOT NULL,
                ubicacion_destino TEXT NOT NULL,
                cantidad REAL NOT NULL,
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                estado TEXT NOT NULL DEFAULT 'Completado',
                observaciones TEXT DEFAULT '',
                FOREIGN KEY (producto_id) REFERENCES productos (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_traslado_num ON traslados_inventario(numero_traslado)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_traslado_fecha ON traslados_inventario(fecha)")

        # 17. Tabla de Compras / Entradas de Mercancía (Inversión en Activo)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS compras_inventario (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_compra TEXT UNIQUE NOT NULL,
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                proveedor_id INTEGER,
                proveedor_nombre TEXT NOT NULL,
                documento_referencia TEXT DEFAULT '',
                ubicacion_destino TEXT NOT NULL DEFAULT 'BODEGA',
                total_compra REAL NOT NULL DEFAULT 0.0,
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                observaciones TEXT DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'Recibida',
                FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_num ON compras_inventario(numero_compra)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_fecha ON compras_inventario(fecha)")

        # 18. Tabla de Detalle de Compras (con Factor de Conversión de Unidades)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS detalle_compras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                compra_id INTEGER NOT NULL,
                producto_id INTEGER NOT NULL,
                codigo_producto TEXT NOT NULL,
                nombre_producto TEXT NOT NULL,
                unidad_compra TEXT NOT NULL,
                factor_conversion REAL NOT NULL DEFAULT 1.0,
                cantidad_comprada REAL NOT NULL,
                cantidad_unidades REAL NOT NULL,
                costo_unidad_compra REAL NOT NULL,
                costo_unitario_convertido REAL NOT NULL,
                subtotal REAL NOT NULL,
                FOREIGN KEY (compra_id) REFERENCES compras_inventario (id) ON DELETE CASCADE,
                FOREIGN KEY (producto_id) REFERENCES productos (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_detcompra_compra ON detalle_compras(compra_id)")

        # 19. Migraciones de Servicios de Proveedores y Precios Varios en productos
        for col_def in [
            "precio_variable INTEGER DEFAULT 0",
            "porcentaje_comision REAL DEFAULT 0.0"
        ]:
            try:
                cursor.execute(f"ALTER TABLE productos ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # 20. Migraciones de Proveedores (NIT, acumulados y métricas)
        for col_def in [
            "total_ventas REAL DEFAULT 0.0",
            "total_comisiones REAL DEFAULT 0.0",
            "total_pagado REAL DEFAULT 0.0",
            "documento_nit TEXT DEFAULT ''"
        ]:
            try:
                cursor.execute(f"ALTER TABLE proveedores ADD COLUMN {col_def}")
            except sqlite3.OperationalError:
                pass

        # 21. Tabla de Cuentas por Pagar a Proveedores (Servicios asociados)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cuentas_por_pagar_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proveedor_id INTEGER NOT NULL,
                proveedor_nombre TEXT NOT NULL,
                id_venta INTEGER NOT NULL,
                numero_venta TEXT,
                codigo_servicio TEXT NOT NULL,
                nombre_servicio TEXT NOT NULL,
                precio_venta REAL NOT NULL,
                porcentaje_comision REAL NOT NULL DEFAULT 0.0,
                monto_comision REAL NOT NULL DEFAULT 0.0,
                monto_por_pagar REAL NOT NULL,
                monto_pagado REAL NOT NULL DEFAULT 0.0,
                saldo_pendiente REAL NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Pendiente', -- 'Pendiente', 'Pagada', 'Abonada', 'Anulada'
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                FOREIGN KEY (proveedor_id) REFERENCES proveedores (id),
                FOREIGN KEY (id_venta) REFERENCES ventas (id_venta)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cxp_prov_id ON cuentas_por_pagar_proveedores(proveedor_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cxp_estado ON cuentas_por_pagar_proveedores(estado)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cxp_venta ON cuentas_por_pagar_proveedores(id_venta)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_cxp_fecha ON cuentas_por_pagar_proveedores(fecha)")

        # 22. Tabla de Liquidaciones y Pagos a Proveedores
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS liquidaciones_proveedores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_recibo TEXT UNIQUE NOT NULL,
                proveedor_id INTEGER NOT NULL,
                proveedor_nombre TEXT NOT NULL,
                monto_liquidado REAL NOT NULL,
                saldo_anterior REAL NOT NULL,
                saldo_restante REAL NOT NULL,
                tipo_pago TEXT NOT NULL DEFAULT 'Total', -- 'Total' o 'Abono Parcial'
                metodo_pago TEXT NOT NULL DEFAULT 'Efectivo', -- 'Efectivo', 'Transferencia'
                referencia TEXT DEFAULT '',
                fecha TEXT NOT NULL,
                hora TEXT NOT NULL,
                mes_anio TEXT NOT NULL,
                usuario TEXT NOT NULL DEFAULT 'Administrador',
                observaciones TEXT DEFAULT '',
                estado TEXT NOT NULL DEFAULT 'Aplicada', -- 'Aplicada', 'Revertida'
                FOREIGN KEY (proveedor_id) REFERENCES proveedores (id)
            )
        """)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_liq_prov_id ON liquidaciones_proveedores(proveedor_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_liq_prov_fecha ON liquidaciones_proveedores(fecha)")

        conn.commit()
        print("✅ Base de datos ventas.db inicializada correctamente.")
        return True
    except Exception as e:
        print(f"❌ Error al crear tablas en ventas.db: {e}")
        return False
    finally:
        conn.close()

if __name__ == "__main__":
    inicializar_base_datos()
