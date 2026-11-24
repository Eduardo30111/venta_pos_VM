#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: usuarios_db.py
Módulo para la gestión de la base de datos local de usuarios del sistema VmPOS.
"""

import sqlite3
import hashlib
import hmac
import os
import logging
from datetime import datetime

logger = logging.getLogger("vmpos.usuarios_db")

try:
    import bcrypt
    _HAS_BCRYPT = True
except ImportError:
    _HAS_BCRYPT = False

# Importar ruta de configuración centralizada
try:
    from interface.config import DB_USUARIOS_PATH as DATABASE_PATH
except ImportError:
    from config import DB_USUARIOS_PATH as DATABASE_PATH

# Módulos disponibles en el sistema
MODULOS_DISPONIBLES = [
    "ventas",
    "inventario",
    "usuarios",
    "reportes",
    "configuracion",
]

CLAVES_INSEGURAS = frozenset({
    "admin123",
    "123456",
    "12345",
    "1234567",
    "12345678",
    "123456789",
    "123456789012",
    "012345678901",
    "admin",
    "administrador",
    "password",
    "password1234",
    "password12345",
    "qwerty",
    "qwertyuiop12",
    "qwerty123456",
    "vmpos",
    "vmpos123",
    "vmpos12345678",
    "000000",
    "000000000000",
    "111111111111",
    "abcdefghijkl",
    "superadmin12",
    "welcome12345",
    "cambiame1234",
    "cambiame2026",
    "seguridad123",
    "colombia2026",
})


def hash_password(password):
    """
    Genera un hash seguro bcrypt rounds=12 (truncado consistente a 72 bytes UTF-8).
    Si el módulo 'bcrypt' no está disponible, genera un RuntimeError controlado
    para impedir de forma absoluta la creación o almacenamiento de contraseñas inseguras.
    """
    if not password:
        return ""
    if not _HAS_BCRYPT:
        raise RuntimeError(
            "El componente de seguridad 'bcrypt' es obligatorio para generar o modificar "
            "contraseñas en VmPOS. Instale la dependencia con: pip install bcrypt"
        )
    pwd_bytes = str(password).encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verificar_password(password_plana, hash_almacenado):
    """
    Verifica una contraseña contra hash bcrypt ($2b$, $2a$, $2y$), sha256 o texto plano legado.
    Utiliza comparación en tiempo constante para evitar ataques de temporización.
    """
    if not password_plana or not hash_almacenado:
        return False
    hash_str = str(hash_almacenado).strip()
    if hash_str.startswith(("$2b$", "$2a$", "$2y$")):
        if _HAS_BCRYPT:
            try:
                pwd_bytes = str(password_plana).encode("utf-8")[:72]
                return bcrypt.checkpw(pwd_bytes, hash_str.encode("utf-8"))
            except Exception:
                return False
        return False
    if len(hash_str) == 64:
        calc_sha = hashlib.sha256(str(password_plana).encode("utf-8")).hexdigest()
        return hmac.compare_digest(calc_sha, hash_str)
    return hmac.compare_digest(str(password_plana), hash_str)


def validar_password_fuerte(password: str) -> tuple:
    """
    Valida que la contraseña cumpla los requisitos de seguridad empresarial:
    - Longitud mínima de 12 caracteres.
    - Al menos una letra mayúscula (A-Z).
    - Al menos una letra minúscula (a-z).
    - Al menos un dígito numérico (0-9).
    - Al menos un carácter especial o símbolo (!@#$%^&*...).
    - No pertenecer a listas de contraseñas comunes, predeterminadas o secuencias simples.
    """
    if not password:
        return False, "La contraseña no puede estar vacía."
    pwd = str(password).strip()
    if len(pwd) < 12:
        return False, f"La contraseña debe tener al menos 12 caracteres (longitud actual: {len(pwd)})."
    p_lower = pwd.lower()
    if p_lower in CLAVES_INSEGURAS:
        return False, "La contraseña ingresada es común o predeterminada. Elija una clave personalizada y robusta."
    if not any(c.isupper() for c in pwd):
        return False, "La contraseña debe contener al menos una letra mayúscula."
    if not any(c.islower() for c in pwd):
        return False, "La contraseña debe contener al menos una letra minúscula."
    if not any(c.isdigit() for c in pwd):
        return False, "La contraseña debe contener al menos un número (0-9)."
    if not any(not c.isalnum() for c in pwd):
        return False, "La contraseña debe contener al menos un carácter especial (!@#$%^&*...)."
    if len(set(pwd)) <= 3:
        return False, "La contraseña no puede componerse de caracteres repetitivos."
    return True, ""


def conectar_usuarios_db():
    """Establece conexión a la base de datos de usuarios con WAL y timeout seguro."""
    ruta = os.environ.get("VMPOS_DB_USUARIOS") or DATABASE_PATH
    os.makedirs(os.path.dirname(os.path.abspath(ruta)), exist_ok=True)
    conn = sqlite3.connect(ruta, timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
    except Exception:
        pass
    return conn


def _is_benign_ddl_error(error_msg: str) -> bool:
    msg = str(error_msg).lower()
    return "duplicate column" in msg or "already exists" in msg


def crear_tablas_iniciales():
    """
    Crea las tablas necesarias en la base de datos si no existen y aplica migraciones DDL.
    Lanza RuntimeError si ocurre cualquier fallo fatal de base de datos (fail-closed).
    """
    conn = None
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                rol TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Activo',
                ultimo_acceso DATETIME,
                fecha_registro DATETIME DEFAULT CURRENT_TIMESTAMP,
                fecha_modificacion DATETIME DEFAULT CURRENT_TIMESTAMP,
                nombre TEXT DEFAULT '',
                apellidos TEXT DEFAULT '',
                tipo_nomina TEXT DEFAULT 'Porcentual',
                salario_diario REAL DEFAULT 0.0,
                comision_porcentaje REAL DEFAULT 0.0,
                comisiones_acumuladas REAL DEFAULT 0.0,
                solicitud_liquidacion DATETIME,
                requiere_cambio_password INTEGER DEFAULT 0
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS permisos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario_id INTEGER,
                modulo TEXT NOT NULL,
                permiso TEXT NOT NULL,
                FOREIGN KEY (usuario_id) REFERENCES usuarios (id) ON DELETE CASCADE
            )
        ''')

        conn.commit()

        migraciones = [
            ("ALTER TABLE usuarios ADD COLUMN comision_porcentaje REAL DEFAULT 0", "comision_porcentaje"),
            ("ALTER TABLE usuarios ADD COLUMN comisiones_acumuladas REAL DEFAULT 0", "comisiones_acumuladas"),
            ("ALTER TABLE usuarios ADD COLUMN solicitud_liquidacion DATETIME", "solicitud_liquidacion"),
            ("ALTER TABLE usuarios ADD COLUMN requiere_cambio_password INTEGER DEFAULT 0", "requiere_cambio_password"),
        ]

        for ddl_sql, campo in migraciones:
            try:
                cursor.execute(ddl_sql)
            except sqlite3.OperationalError as e_ddl:
                if not _is_benign_ddl_error(str(e_ddl)):
                    logger.critical("Error fatal en migración DDL de usuarios (%s): %s", campo, e_ddl)
                    raise RuntimeError(f"Fallo crítico en migración DDL de usuarios ({campo}): {e_ddl}") from e_ddl

        conn.commit()
        logger.info("Tablas de usuarios creadas/verificadas correctamente.")
        return True
    except RuntimeError:
        raise
    except Exception as e:
        logger.critical("Error fatal al crear/verificar tablas de usuarios: %s", e)
        raise RuntimeError(f"Error crítico inicializando base de datos de usuarios: {e}") from e
    finally:
        if conn is not None:
            conn.close()


def hay_administrador() -> bool:
    """
    Verifica si existe al menos un usuario con rol de Administrador activo en el sistema.
    Política fail-closed: ante cualquier error de acceso o corrupción de la base de datos,
    lanza RuntimeError en lugar de retornar False (evita activar erróneamente el alta inicial).
    """
    conn = None
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(id) FROM usuarios WHERE LOWER(rol) IN ('administrador', 'admin') AND LOWER(estado) = 'activo'"
        )
        row = cursor.fetchone()
        return bool(row and int(row[0] or 0) > 0)
    except Exception as e:
        logger.critical("Error crítico verificando existencia de administrador: %s", e)
        raise RuntimeError(f"No se pudo verificar el estado de administradores en usuarios.db: {e}") from e
    finally:
        if conn is not None:
            conn.close()


def crear_administrador_inicial(usuario, password, nombre="Administrador", apellidos="Principal"):
    """
    Crea el primer administrador en una instalación nueva (operación estricta de un solo uso).
    Valida fortaleza de contraseña, bloquea si ya existe un administrador y evita claves universales.
    """
    valido, mensaje = validar_password_fuerte(password)
    if not valido:
        raise ValueError(mensaje)

    u_limpio = (usuario or "").strip()
    if len(u_limpio) < 3:
        raise ValueError("El nombre de usuario debe tener al menos 3 caracteres.")

    conn = conectar_usuarios_db()
    cursor = conn.cursor()
    try:
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT COUNT(id) FROM usuarios WHERE LOWER(rol) IN ('administrador', 'admin')"
        )
        ya_hay_admin = int((cursor.fetchone() or [0])[0] or 0) > 0
        if ya_hay_admin:
            conn.rollback()
            raise PermissionError(
                "El sistema ya cuenta con un administrador configurado. "
                "La activación inicial es de un solo uso."
            )

        cursor.execute("SELECT id FROM usuarios WHERE LOWER(usuario) = LOWER(?)", (u_limpio,))
        if cursor.fetchone():
            conn.rollback()
            raise ValueError(f"El usuario '{u_limpio}' ya existe en el sistema.")

        password_hash = hash_password(password.strip())
        cursor.execute('''
            INSERT INTO usuarios (
                usuario, password, rol, estado, fecha_registro, fecha_modificacion,
                nombre, apellidos, requiere_cambio_password
            ) VALUES (?, ?, 'Administrador', 'Activo', ?, ?, ?, ?, 0)
        ''', (u_limpio, password_hash, datetime.now(), datetime.now(), nombre.strip(), apellidos.strip()))
        conn.commit()
        logger.info("Administrador inicial '%s' creado exitosamente.", u_limpio)
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def insertar_usuario(
    usuario,
    password,
    rol,
    estado="Activo",
    comision_porcentaje=0.0,
    nombre="",
    apellidos="",
    tipo_nomina="Porcentual",
    salario_diario=0.0,
):
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()

        cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
        if cursor.fetchone():
            logger.warning("El usuario '%s' ya existe.", usuario)
            conn.close()
            return False

        password_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO usuarios (
                usuario, password, rol, estado, fecha_registro, fecha_modificacion,
                comision_porcentaje, comisiones_acumuladas, nombre, apellidos,
                tipo_nomina, salario_diario, requiere_cambio_password
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, 0)
        ''', (
            usuario,
            password_hash,
            rol,
            estado,
            datetime.now(),
            datetime.now(),
            comision_porcentaje,
            nombre,
            apellidos,
            tipo_nomina,
            salario_diario,
        ))

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("Error al insertar usuario: %s", e)
        return False


def obtener_usuarios():
    """Obtiene todos los usuarios de la base de datos local."""
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()

        cursor.execute('''
            SELECT id, usuario, rol, estado, ultimo_acceso, fecha_registro,
                   comision_porcentaje, comisiones_acumuladas, solicitud_liquidacion,
                   requiere_cambio_password
            FROM usuarios
            ORDER BY fecha_registro DESC
        ''')

        usuarios = []
        for row in cursor.fetchall():
            usuarios.append({
                'id': row[0],
                'usuario': row[1],
                'rol': row[2],
                'estado': row[3],
                'ultimo_acceso': row[4] if row[4] else "Nunca",
                'fecha_registro': row[5],
                'comision_porcentaje': row[6] if row[6] is not None else 0.0,
                'comisiones_acumuladas': row[7] if row[7] is not None else 0.0,
                'solicitud_liquidacion': row[8],
                'requiere_cambio_password': bool(row[9]) if len(row) > 9 else False,
            })

        conn.close()
        return usuarios
    except Exception as e:
        logger.error("Error al obtener usuarios: %s", e)
        return []


def actualizar_usuario_db(
    id_usuario,
    usuario=None,
    rol=None,
    estado=None,
    password=None,
    comision_porcentaje=None,
    nombre=None,
    apellidos=None,
    tipo_nomina=None,
    salario_diario=None,
    requiere_cambio_password=None,
):
    """
    Actualiza la información de un usuario existente.
    Si se actualiza la contraseña a un valor seguro no predeterminado, desactiva requiere_cambio_password.
    """
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()

        campos_actualizar = []
        valores = []

        if usuario:
            campos_actualizar.append("usuario = ?")
            valores.append(usuario)
        if rol:
            campos_actualizar.append("rol = ?")
            valores.append(rol)
        if estado:
            campos_actualizar.append("estado = ?")
            valores.append(estado)
        if password:
            campos_actualizar.append("password = ?")
            valores.append(hash_password(password))
            if requiere_cambio_password is None and password.strip().lower() not in CLAVES_INSEGURAS:
                campos_actualizar.append("requiere_cambio_password = ?")
                valores.append(0)
        if requiere_cambio_password is not None:
            campos_actualizar.append("requiere_cambio_password = ?")
            valores.append(1 if requiere_cambio_password else 0)
        if comision_porcentaje is not None:
            campos_actualizar.append("comision_porcentaje = ?")
            valores.append(comision_porcentaje)
        if nombre is not None:
            campos_actualizar.append("nombre = ?")
            valores.append(nombre)
        if apellidos is not None:
            campos_actualizar.append("apellidos = ?")
            valores.append(apellidos)
        if tipo_nomina is not None:
            campos_actualizar.append("tipo_nomina = ?")
            valores.append(tipo_nomina)
        if salario_diario is not None:
            campos_actualizar.append("salario_diario = ?")
            valores.append(salario_diario)

        campos_actualizar.append("fecha_modificacion = ?")
        valores.append(datetime.now())
        valores.append(id_usuario)

        if campos_actualizar:
            consulta = f"UPDATE usuarios SET {', '.join(campos_actualizar)} WHERE id = ?"
            cursor.execute(consulta, valores)
            conn.commit()

        conn.close()
        return True
    except Exception as e:
        logger.error("Error al actualizar usuario: %s", e)
        return False


def eliminar_usuario_db(id_usuario):
    """Elimina un usuario de la base de datos local."""
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (id_usuario,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("Error al eliminar usuario: %s", e)
        return False


def obtener_usuario_por_credenciales(usuario, password):
    """
    Verifica las credenciales de un usuario y retorna su información.
    Soporta contraseñas con hash bcrypt, sha256 y texto plano legado con rehash automático a bcrypt.
    Aplica mínimo privilegio por defecto ('Operario') si el rol falta.
    """
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()

        cursor.execute("PRAGMA table_info(usuarios)")
        cols = [r[1] for r in cursor.fetchall()]

        cursor.execute("SELECT * FROM usuarios WHERE usuario = ? AND estado = 'Activo'", (usuario,))
        resultado = cursor.fetchone()

        if resultado:
            row = dict(zip(cols, resultado))
            uid = row.get("id")
            u_nom = row.get("usuario")
            rol = row.get("rol") or "Operario"
            estado = row.get("estado", "Activo")
            u_acc = row.get("ultimo_acceso")
            f_reg = row.get("fecha_registro")
            com_pct = row.get("comision_porcentaje", 0.0)
            com_acum = row.get("comisiones_acumuladas", 0.0)
            pass_guardada = row.get("password") or row.get("contrasena")
            nombre_u = row.get("nombre") or u_nom
            apell_u = row.get("apellidos", "")
            req_cambio = bool(row.get("requiere_cambio_password", 0))

            if verificar_password(password, pass_guardada):
                pass_str = str(pass_guardada or "")
                if not pass_str.startswith(("$2b$", "$2a$", "$2y$")) and _HAS_BCRYPT:
                    nuevo_hash = hash_password(password)
                    cursor.execute(
                        "UPDATE usuarios SET password = ?, fecha_modificacion = ? WHERE id = ?",
                        (nuevo_hash, datetime.now(), uid),
                    )

                cursor.execute(
                    "UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?",
                    (datetime.now(), uid),
                )
                conn.commit()

                debe_cambiar = bool(req_cambio or (str(password).strip().lower() == "admin123"))

                usuario_info = {
                    'id': uid,
                    'usuario': u_nom,
                    'nombre': nombre_u or u_nom,
                    'apellidos': apell_u or "",
                    'rol': rol,
                    'estado': estado,
                    'ultimo_acceso': u_acc,
                    'fecha_registro': f_reg,
                    'permisos': str(rol).lower(),
                    'comision_porcentaje': com_pct if com_pct is not None else 0.0,
                    'comisiones_acumuladas': com_acum if com_acum is not None else 0.0,
                    'requiere_cambio_password': debe_cambiar,
                }

                conn.close()
                return usuario_info

        conn.close()
        return None
    except Exception as e:
        logger.error("Error al verificar credenciales: %s", e)
        return None


def pedir_liquidacion(id_usuario):
    """Registra la hora en que el empleado pidió liquidación."""
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET solicitud_liquidacion = ? WHERE id = ?", (datetime.now(), id_usuario))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.error("Error al pedir liquidación: %s", e)
        return False


def liquidar_comisiones(id_usuario):
    """Pone en cero las comisiones y limpia la solicitud."""
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        cursor.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id = ?", (id_usuario,))
        resultado = cursor.fetchone()
        comisiones = resultado[0] if resultado else 0.0

        cursor.execute("UPDATE usuarios SET comisiones_acumuladas = 0, solicitud_liquidacion = NULL WHERE id = ?", (id_usuario,))
        conn.commit()
        conn.close()
        return comisiones
    except Exception as e:
        logger.error("Error al liquidar comisiones: %s", e)
        return 0.0


def obtener_permisos_por_usuario(usuario_id):
    """Obtiene los permisos específicos de un usuario."""
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT modulo, permiso FROM permisos WHERE usuario_id = ?",
            (usuario_id,),
        )
        permisos = cursor.fetchall()
        conn.close()
        return permisos
    except Exception as e:
        logger.error("Error al obtener permisos: %s", e)
        return []


def inicializar_admin_default(forzar_legacy: bool = False):
    """
    DESHABILITADO POR POLÍTICA DE SEGURIDAD:
    No crea credenciales universales ('admin/admin123') en operación normal.
    Únicamente permite aprovisionamiento automatizado si se suministra una contraseña fuerte
    explícita en la variable de entorno VMPOS_ADMIN_PASSWORD y no existe ningún administrador,
    o en entornos de pruebas aislados con forzar_legacy=True (marcado con requiere_cambio_password=1).
    En instalaciones interactivas debe usarse crear_administrador_inicial().
    """
    if hay_administrador():
        return False

    if forzar_legacy:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        p_hash = hash_password("admin123")
        cursor.execute('''
            INSERT INTO usuarios (
                usuario, password, rol, estado, fecha_registro, fecha_modificacion,
                nombre, apellidos, requiere_cambio_password
            ) VALUES ('admin', ?, 'Administrador', 'Activo', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 'Admin', 'Legacy', 1)
        ''', (p_hash,))
        conn.commit()
        conn.close()
        return True

    env_pwd = (os.environ.get("VMPOS_ADMIN_PASSWORD") or "").strip()
    env_usr = (os.environ.get("VMPOS_ADMIN_USER") or "admin").strip() or "admin"
    if not env_pwd:
        raise RuntimeError(
            "La creación automática de 'admin/admin123' está deshabilitada por seguridad. "
            "Use el asistente de activación inicial (crear_administrador_inicial) "
            "o defina VMPOS_ADMIN_PASSWORD con una contraseña segura."
        )
    return crear_administrador_inicial(env_usr, env_pwd, nombre="Administrador", apellidos="Principal")


if __name__ == "__main__":
    print("🚀 Inicializando esquema de base de datos de usuarios...")
    crear_tablas_iniciales()
    if hay_administrador():
        print("✅ Base de datos de usuarios lista (administrador existente verificado).")
    else:
        print("ℹ️ Sistema sin administrador inicial. Ejecute la aplicación para completar la activación segura.")
