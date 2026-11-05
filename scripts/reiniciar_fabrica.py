#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Restauración de Fábrica para VmPOS.
Limpia todas las ventas de prueba, clientes de prueba, compras, deudas, abonos y sesiones de caja,
dejando el sistema 100% limpio como nuevo de fábrica con el usuario administrador por defecto:
- Usuario: admin
- Contraseña: admin123
"""

import os
import sys
import sqlite3
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)

print("=" * 70)
print("       RESTAURACIÓN A VALORES DE FÁBRICA — VmPOS")
print("=" * 70)

# 1. Limpieza de base de datos local SQLite (ventas.db)
ventas_db = os.path.join(PROJECT_ROOT, "database", "ventas.db")
if os.path.exists(ventas_db):
    print("\n[1/3] Limpiando database/ventas.db...")
    conn = sqlite3.connect(ventas_db)
    cur = conn.cursor()

    tablas_a_vaciar = [
        "ventas", "detalle_ventas", "pagos_venta", "auditoria_ventas",
        "movimientos_financieros", "gastos", "gastos_recurrentes",
        "sesiones_caja", "movimientos_caja", "clientes",
        "cuentas_por_pagar_proveedores", "liquidaciones_proveedores",
        "compras_inventario", "detalle_compras", "movimientos_inventario",
        "traslados_inventario", "reportes", "proveedores", "productos"
    ]

    for t in tablas_a_vaciar:
        try:
            cur.execute(f"DELETE FROM {t};")
            print(f"  ✓ Vaciada tabla: {t}")
        except sqlite3.OperationalError:
            pass

    try:
        cur.execute("DELETE FROM sqlite_sequence;")
    except Exception:
        pass

    # Restablecer configuración de negocio inicial limpia
    try:
        cur.execute("DELETE FROM configuracion_negocio WHERE clave='business_config';")
        cfg_default = {
            "nombre_negocio": "VmPOS",
            "razon_social": "Mi Negocio",
            "subtitulo_negocio": "Punto de Venta Profesional",
            "tipo_documento_fiscal": "NIT",
            "nit": "",
            "regimen_fiscal": "",
            "direccion": "",
            "ciudad": "",
            "telefono": "",
            "email": "",
            "eslogan": "Sistema de Punto de Venta y Facturación",
            "encabezado_recibo": "",
            "tipo_comprobante": "FACTURA DE VENTA POS",
            "prefijo_comprobante": "POS",
            "color_barra": "#0284C7",
            "color_login": "#1E40AF",
            "logo_path": "",
            "logo_thermal_path": ""
        }
        cur.execute("INSERT OR REPLACE INTO configuracion_negocio (clave, valor_json, actualizado_en) VALUES (?, ?, datetime('now'));",
                    ('business_config', json.dumps(cfg_default)))
        print("  ✓ Configuración de negocio restablecida a valores por defecto.")
    except Exception as e:
        print(f"  ⚠️ Aviso en configuracion_negocio: {e}")

    conn.commit()
    conn.close()

# 2. Limpieza de usuarios (usuarios.db)
usuarios_db = os.path.join(PROJECT_ROOT, "database", "usuarios.db")
if os.path.exists(usuarios_db):
    print("\n[2/3] Limpiando database/usuarios.db...")
    conn = sqlite3.connect(usuarios_db)
    cur = conn.cursor()

    for t in ["asistencia", "nomina_devengos", "nomina_pagos"]:
        try:
            cur.execute(f"DELETE FROM {t};")
            print(f"  ✓ Vaciada tabla: {t}")
        except Exception:
            pass

    try:
        # Eliminar todos los usuarios excepto 'admin'
        cur.execute("DELETE FROM usuarios WHERE usuario != 'admin';")
        # Asegurar usuario admin
        cur.execute("SELECT id FROM usuarios WHERE usuario = 'admin';")
        row = cur.fetchone()
        if not row:
            cur.execute("""
                INSERT INTO usuarios (usuario, password, rol, estado, nombre)
                VALUES ('admin', 'admin123', 'Administrador', 'Activo', 'Administrador');
            """)
            print("  ✓ Creado usuario administrador predeterminado (admin / admin123)")
        else:
            cur.execute("""
                UPDATE usuarios SET password = 'admin123', rol = 'Administrador', estado = 'Activo'
                WHERE usuario = 'admin';
            """)
            print("  ✓ Usuario 'admin' restablecido con contraseña: admin123")
    except Exception as e:
        print(f"  ⚠️ Error en usuarios: {e}")

    conn.commit()
    conn.close()

# 3. Limpieza de red (network_config.json)
net_file = os.path.join(PROJECT_ROOT, "network_config.json")
default_net = {
    "tipo_nodo": "servidor",
    "servidor_ip": "127.0.0.1",
    "servidor_puerto": 8000
}
with open(net_file, "w", encoding="utf-8") as f:
    json.dump(default_net, f, indent=2)
print("\n[3/3] network_config.json restablecido a Servidor Local (127.0.0.1:8000).")

print("\n" + "=" * 70)
print("  🎉 ¡RESTAURACIÓN DE FÁBRICA COMPLETADA CON ÉXITO!")
print("  El sistema está limpio como recién instalado.")
print("  Usuario: admin | Contraseña: admin123")
print("=" * 70)
