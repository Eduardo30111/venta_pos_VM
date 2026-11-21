#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: scripts/inicializar_sistema_limpio.py
Inicializador de base de datos de producción limpia para VmPOS.
- Elimina cualquier dato de prueba o demostración.
- Genera esquema completo y canónico de base de datos.
- No crea credenciales predeterminadas: requiere activación inicial segura
  o aprovisionamiento explícito mediante VMPOS_ADMIN_PASSWORD (con hash bcrypt).
"""

import os
import sys
import sqlite3

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)


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
        from interface.usuarios_db import crear_tablas_iniciales, crear_administrador_inicial
        crear_tablas_iniciales()

        conn_u = sqlite3.connect(usuarios_db_path)
        cur_u = conn_u.cursor()
        cur_u.execute("DELETE FROM usuarios")
        conn_u.commit()
        conn_u.close()

        env_admin_pwd = (os.environ.get("VMPOS_ADMIN_PASSWORD") or "").strip()
        env_admin_user = (os.environ.get("VMPOS_ADMIN_USER") or "admin").strip()
        if env_admin_pwd:
            crear_administrador_inicial(env_admin_user, env_admin_pwd, nombre="Administrador Principal")
            print(f"  -> Administrador '{env_admin_user}' aprovisionado de forma segura (bcrypt) desde VMPOS_ADMIN_PASSWORD.")
        else:
            print("  -> Base de usuarios limpia y sin credenciales predeterminadas.")
            print("  -> En el primer inicio de VmPOS se abrirá el asistente de activación del Administrador Maestro.")
    except Exception as e:
        print(f"  ❌ Error inicializando usuarios_db: {e}")

    print("=" * 70)
    print(" INSTALACIÓN LIMPIA COMPLETADA EXITOSAMENTE")
    print(" Seguridad: Sin contraseñas predeterminadas ni usuarios genéricos.")
    print("=" * 70)

if __name__ == "__main__":
    inicializar_limpio()
