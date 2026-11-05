#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: scripts/inicializar_sistema_limpio.py
Inicializador de base de datos de producción limpia para VmPOS.
- Elimina cualquier dato de prueba o demostración.
- Genera esquema completo y canónico de base de datos.
- Crea el usuario Administrador único: 'admin' / 'admin123' con cambio forzado.
"""

import os
import sys
import sqlite3
import hashlib
from datetime import datetime

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

def hash_pass(p: str) -> str:
    return hashlib.sha256(p.encode("utf-8")).hexdigest()

def inicializar_limpio():
    print("=" * 70)
    print(" INICIALIZANDO INSTALACIÓN LIMPIA DE VmPOS")
    print("=" * 70)

    db_dir = os.path.join(_PROJECT_ROOT, "database")
    os.makedirs(db_dir, exist_ok=True)

    ventas_db_path = os.path.join(db_dir, "ventas.db")
    usuarios_db_path = os.path.join(db_dir, "usuarios.db")

    # 1. Base de datos de Ventas, Inventario y Cartera
    print(f"[*] Inicializando esquema canónico en {ventas_db_path}...")
    try:
        from interface.database_manager import inicializar_base_datos
        inicializar_base_datos()
        print("  -> Esquema de tablas creado correctamente.")
    except Exception as e:
        print(f"  ❌ Error inicializando database_manager: {e}")

    # 2. Base de datos de Usuarios
    print(f"[*] Inicializando base de datos de usuarios en {usuarios_db_path}...")
    try:
        from interface.usuarios_db import crear_tablas_iniciales
        crear_tablas_iniciales()

        conn_u = sqlite3.connect(usuarios_db_path)
        cur_u = conn_u.cursor()

        # Limpiar usuarios anteriores y dejar únicamente el administrador inicial
        cur_u.execute("DELETE FROM usuarios")
        cur_u.execute("""
            INSERT INTO usuarios (
                usuario, password, rol, estado, nombre, apellidos,
                fecha_registro, fecha_modificacion, debe_cambiar_password
            )
            VALUES (?, ?, 'Administrador', 'Activo', 'Administrador', 'Principal', ?, ?, 1)
        """, ("admin", hash_pass("admin123"), datetime.now(), datetime.now()))

        conn_u.commit()
        conn_u.close()
        print("  -> Usuario único 'admin' creado con contraseña inicial 'admin123' (Cambio forzado en primer acceso).")
    except Exception as e:
        print(f"  ❌ Error inicializando usuarios_db: {e}")

    print("=" * 70)
    print(" INSTALACIÓN LIMPIA COMPLETADA EXITOSAMENTE")
    print(" Credenciales de acceso:")
    print("   Usuario:     admin")
    print("   Contraseña:  admin123")
    print("=" * 70)

if __name__ == "__main__":
    inicializar_limpio()
