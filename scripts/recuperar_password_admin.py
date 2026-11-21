#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Recuperación Segura de Contraseña de Administrador para VmPOS.
Archivo: scripts/recuperar_password_admin.py

Permite a un operador local autorizado con acceso a la consola restablecer
la contraseña de un administrador legítimo que haya olvidado sus credenciales,
respetando la política de contraseñas de al menos 12 caracteres y forzando
el cambio obligatorio en el próximo inicio de sesión.
"""

import os
import sys
import sqlite3
import secrets
import string
import argparse
from datetime import datetime

# Agregar la raíz del proyecto al path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from interface.usuarios_db import (
    conectar_usuarios_db,
    hash_password,
    validar_password_fuerte,
)


def generar_password_temporal_segura(longitud: int = 16) -> str:
    """Genera una contraseña temporal de alta entropía que cumple todas las reglas de complejidad."""
    if longitud < 12:
        longitud = 12
    mayus = string.ascii_uppercase
    minus = string.ascii_lowercase
    digitos = string.digits
    simbolos = "!@#$%^&*()_+-="

    # Garantizar al menos un carácter de cada categoría
    pwd = [
        secrets.choice(mayus),
        secrets.choice(minus),
        secrets.choice(digitos),
        secrets.choice(simbolos),
    ]
    todos = mayus + minus + digitos + simbolos
    pwd += [secrets.choice(todos) for _ in range(longitud - len(pwd))]
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


def listar_administradores():
    """Lista los administradores registrados en la base de datos local."""
    conn = conectar_usuarios_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, usuario, rol, estado, nombre, apellidos, ultimo_acceso FROM usuarios "
            "WHERE LOWER(rol) IN ('administrador', 'admin') ORDER BY id ASC"
        )
        return cur.fetchall()
    finally:
        conn.close()


def restablecer_password_admin(usuario: str, nueva_clave: str = None, generar_temporal: bool = True) -> tuple:
    """
    Restablece la contraseña del administrador indicado:
    - Retorna (True, clave_plana, "mensaje") o (False, None, "error")
    """
    usr_clean = (usuario or "").strip()
    if not usr_clean:
        return False, None, "Debe especificar un nombre de usuario válido."

    conn = conectar_usuarios_db()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, usuario, rol FROM usuarios WHERE LOWER(usuario) = LOWER(?)", (usr_clean,))
        row = cur.fetchone()
        if not row:
            return False, None, f"El usuario '{usr_clean}' no existe en la base de datos."

        uid, usr_real, rol = row
        if str(rol).lower() not in ("administrador", "admin"):
            return False, None, f"El usuario '{usr_real}' tiene rol '{rol}'. Este procedimiento solo aplica a administradores."

        if generar_temporal or not nueva_clave:
            clave_final = generar_password_temporal_segura(16)
            debe_cambiar = 1
        else:
            valido, msg = validar_password_fuerte(nueva_clave)
            if not valido:
                return False, None, f"La nueva contraseña no cumple los requisitos: {msg}"
            clave_final = nueva_clave
            debe_cambiar = 0

        p_hash = hash_password(clave_final)
        ahora = datetime.now()
        cur.execute(
            "UPDATE usuarios SET password = ?, requiere_cambio_password = ?, fecha_modificacion = ? WHERE id = ?",
            (p_hash, debe_cambiar, ahora, uid)
        )
        conn.commit()
        return True, clave_final, f"Contraseña actualizada exitosamente para '{usr_real}'."
    except Exception as e:
        return False, None, f"Error en base de datos: {e}"
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Recuperación Segura de Contraseña de Administrador - VmPOS")
    parser.add_argument("--usuario", "-u", type=str, help="Nombre del usuario administrador a restablecer")
    parser.add_argument("--password", "-p", type=str, help="Nueva contraseña robusta (opcional, mínimo 12 caracteres)")
    parser.add_argument("--generar-temporal", "-g", action="store_true", help="Genera una contraseña temporal segura de 16 caracteres")
    parser.add_argument("--listar", "-l", action="store_true", help="Lista los administradores registrados")

    args = parser.parse_args()

    print("=" * 70)
    print("🔐 VmPOS - UTILIDAD SEGURA DE RECUPERACIÓN DE ADMINISTRADOR")
    print("=" * 70)

    if args.listar:
        admins = listar_administradores()
        if not admins:
            print("⚠️ No se encontraron administradores registrados en la base de datos.")
        else:
            print(f"Se encontraron {len(admins)} administrador(es):")
            for a in admins:
                print(f"  • ID {a[0]}: Usuario='{a[1]}' | Nombre='{a[4]} {a[5]}' | Estado={a[3]} | Último acceso={a[6]}")
        return

    usuario_target = args.usuario
    if not usuario_target:
        admins = listar_administradores()
        if not admins:
            print("❌ No hay administradores en la base de datos. Use el asistente de activación inicial.")
            return
        print("Administradores disponibles:")
        for i, a in enumerate(admins, 1):
            print(f"  [{i}] {a[1]} ({a[4]} {a[5]})")
        try:
            sel = input("\nIngrese el nombre del usuario a recuperar: ").strip()
            if not sel:
                print("Operación cancelada.")
                return
            usuario_target = sel
        except (KeyboardInterrupt, EOFError):
            print("\nOperación cancelada.")
            return

    nueva_pwd = args.password
    gen_temp = args.generar_temporal or (not nueva_pwd)

    ok, clave_generada, mensaje = restablecer_password_admin(
        usuario=usuario_target,
        nueva_clave=nueva_pwd,
        generar_temporal=gen_temp
    )

    if ok:
        print("\n✅ RECUPERACIÓN EXITOSA:")
        print(f"  Usuario: {usuario_target}")
        print(f"  Nueva contraseña temporal: {clave_generada}")
        print("  Requisito: El usuario deberá cambiarla obligatoriamente en su próximo inicio de sesión.")
        print("\nGuarde esta clave en un lugar seguro y entréguela directamente al administrador autorizado.")
    else:
        print(f"\n❌ ERROR: {mensaje}")
        sys.exit(1)


if __name__ == "__main__":
    main()
