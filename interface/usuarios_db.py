#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Archivo: usuarios_db.py
Módulo para la gestión de la base de datos de usuarios del sistema VmPOS.
"""

import sqlite3
import hashlib
import os
from datetime import datetime

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
    "configuracion"
]

def hash_password(password):
    """
    Genera un hash SHA-256 de la contraseña.
    """
    return hashlib.sha256(password.encode()).hexdigest()

def crear_tablas_iniciales():
    """
    Crea las tablas necesarias en la base de datos si no existen.
    """
    try:
        conn = conectar_usuarios_db()
        cursor = conn.cursor()
        
        # Crear tabla de usuarios
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
                solicitud_liquidacion DATETIME
            )
        ''')
        
        # Crear tabla de permisos (para funcionalidades futuras)
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

        # Migraciones (agregar columnas si no existen)
        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN comision_porcentaje REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN comisiones_acumuladas REAL DEFAULT 0")
        except sqlite3.OperationalError:
            pass
        try:
            cursor.execute("ALTER TABLE usuarios ADD COLUMN solicitud_liquidacion DATETIME")
        except sqlite3.OperationalError:
            pass

        conn.commit()
        conn.close()
        print("✅ Tablas de usuarios creadas/verificadas correctamente.")
        return True
        
    except Exception as e:
        print(f"❌ Error al crear tablas: {e}")
        return False

def insertar_usuario(usuario, password, rol, estado="Activo", comision_porcentaje=0.0, nombre="", apellidos="", tipo_nomina="Porcentual", salario_diario=0.0):
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Verificar si el usuario ya existe
        cursor.execute("SELECT id FROM usuarios WHERE usuario = ?", (usuario,))
        if cursor.fetchone():
            print(f"⚠️ El usuario '{usuario}' ya existe.")
            conn.close()
            return False
        
        # Insertar nuevo usuario
        password_hash = hash_password(password)
        cursor.execute('''
            INSERT INTO usuarios (usuario, password, rol, estado, fecha_registro, fecha_modificacion, comision_porcentaje, comisiones_acumuladas, nombre, apellidos, tipo_nomina, salario_diario)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
        ''', (usuario, password_hash, rol, estado, datetime.now(), datetime.now(), comision_porcentaje, nombre, apellidos, tipo_nomina, salario_diario))
        
        conn.commit()
        conn.close()
        print(f"✅ Usuario '{usuario}' creado correctamente.")
        return True
        
    except Exception as e:
        print(f"❌ Error al insertar usuario: {e}")
        return False

def obtener_usuarios():
    """
    Obtiene todos los usuarios de la base de datos.
    
    Returns:
        list: Lista de diccionarios con información de usuarios
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT id, usuario, rol, estado, ultimo_acceso, fecha_registro, comision_porcentaje, comisiones_acumuladas, solicitud_liquidacion
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
                'solicitud_liquidacion': row[8]
            })
        
        conn.close()
        return usuarios
        
    except Exception as e:
        print(f"❌ Error al obtener usuarios: {e}")
        return []

def actualizar_usuario_db(id_usuario, usuario=None, rol=None, estado=None, password=None, comision_porcentaje=None, nombre=None, apellidos=None, tipo_nomina=None, salario_diario=None):
    """
    Actualiza la información de un usuario existente.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Construir la consulta dinámicamente
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
        
        # Siempre actualizar fecha de modificación
        campos_actualizar.append("fecha_modificacion = ?")
        valores.append(datetime.now())
        
        # Agregar ID al final para la condición WHERE
        valores.append(id_usuario)
        
        if campos_actualizar:
            consulta = f"UPDATE usuarios SET {', '.join(campos_actualizar)} WHERE id = ?"
            cursor.execute(consulta, valores)
            conn.commit()
        
        conn.close()
        print(f"✅ Usuario con ID {id_usuario} actualizado correctamente.")
        return True
        
    except Exception as e:
        print(f"❌ Error al actualizar usuario: {e}")
        return False

def eliminar_usuario_db(id_usuario):
    """
    Elimina un usuario de la base de datos.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM usuarios WHERE id = ?", (id_usuario,))
        conn.commit()
        conn.close()
        
        print(f"✅ Usuario con ID {id_usuario} eliminado correctamente.")
        return True
        
    except Exception as e:
        print(f"❌ Error al eliminar usuario: {e}")
        return False

def obtener_usuario_por_credenciales(usuario, password):
    """
    Verifica las credenciales de un usuario y retorna su información.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        password_hash = hash_password(password)
        cursor.execute('''
            SELECT id, usuario, rol, estado, ultimo_acceso, fecha_registro, comision_porcentaje, comisiones_acumuladas
            FROM usuarios
            WHERE usuario = ? AND password = ? AND estado = 'Activo'
        ''', (usuario, password_hash))
        
        resultado = cursor.fetchone()
        
        if resultado:
            # Actualizar último acceso
            cursor.execute('''
                UPDATE usuarios SET ultimo_acceso = ?
                WHERE id = ?
            ''', (datetime.now(), resultado[0]))
            conn.commit()
            
            usuario_info = {
                'id': resultado[0],
                'usuario': resultado[1],
                'rol': resultado[2],
                'estado': resultado[3],
                'ultimo_acceso': resultado[4],
                'fecha_registro': resultado[5],
                'permisos': resultado[2].lower(),  # Para compatibilidad con el sistema existente
                'comision_porcentaje': resultado[6] if resultado[6] is not None else 0.0,
                'comisiones_acumuladas': resultado[7] if resultado[7] is not None else 0.0
            }
            
            conn.close()
            return usuario_info
        
        conn.close()
        return None
        
    except Exception as e:
        print(f"❌ Error al verificar credenciales: {e}")
        return None

def pedir_liquidacion(id_usuario):
    """Registra la hora en que el empleado pidió liquidación."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios SET solicitud_liquidacion = ? WHERE id = ?", (datetime.now(), id_usuario))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error al pedir liquidación: {e}")
        return False

def liquidar_comisiones(id_usuario):
    """Pone en cero las comisiones y limpia la solicitud."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Obtener cuánto se le va a pagar para registrarlo como gasto o simplemente devolverlo
        cursor.execute("SELECT comisiones_acumuladas FROM usuarios WHERE id = ?", (id_usuario,))
        resultado = cursor.fetchone()
        comisiones = resultado[0] if resultado else 0.0

        cursor.execute("UPDATE usuarios SET comisiones_acumuladas = 0, solicitud_liquidacion = NULL WHERE id = ?", (id_usuario,))
        conn.commit()
        conn.close()
        return comisiones
    except Exception as e:
        print(f"❌ Error al liquidar: {e}")
        return 0.0

def obtener_permisos_por_usuario(usuario_id):
    """
    Obtiene los permisos específicos de un usuario.
    
    Args:
        usuario_id (int): ID del usuario
    
    Returns:
        list: Lista de permisos del usuario
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT modulo, permiso
            FROM permisos
            WHERE usuario_id = ?
        ''', (usuario_id,))
        
        permisos = cursor.fetchall()
        conn.close()
        
        return permisos
        
    except Exception as e:
        print(f"❌ Error al obtener permisos: {e}")
        return []

def inicializar_admin_default():
    """
    Crea un usuario administrador por defecto si no existe ningún administrador.
    """
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        cursor = conn.cursor()
        
        # Verificar si existe algún administrador
        cursor.execute("SELECT id FROM usuarios WHERE rol = 'Administrador'")
        if not cursor.fetchone():
            # Crear administrador por defecto
            password_hash = hash_password("admin123")
            cursor.execute('''
                INSERT INTO usuarios (usuario, password, rol, estado, fecha_registro, fecha_modificacion)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', ("admin", password_hash, "Administrador", "Activo", datetime.now(), datetime.now()))
            conn.commit()
            print("✅ Usuario administrador por defecto creado: admin/admin123")
        
        conn.close()
        
    except Exception as e:
        print(f"❌ Error al crear administrador por defecto: {e}")

# Función para migrar usuarios existentes (si los tienes en otro formato)
def migrar_usuarios_existentes():
    """
    Función auxiliar para migrar usuarios desde el sistema de login actual.
    Puedes usar esta función para añadir los usuarios hardcodeados del inicio_sesion.py
    """
    # Usuarios del sistema actual
    usuarios_sistema = [
        {"usuario": "eduardo", "password": "2121", "rol": "Administrador"},
        {"usuario": "andres", "password": "2180", "rol": "Vendedor"}
    ]
    
    for user in usuarios_sistema:
        insertar_usuario(
            user["usuario"],
            user["password"], 
            user["rol"],
            "Activo"
        )

# Ejecutar inicialización al importar el módulo
if __name__ == "__main__":
    print("🚀 Inicializando base de datos de usuarios...")
    crear_tablas_iniciales()
    inicializar_admin_default()
    # Descomenta la siguiente línea si quieres migrar los usuarios del sistema actual
    # migrar_usuarios_existentes()
    print("✅ Base de datos de usuarios lista.")
def conectar_usuarios_db():
    import sqlite3
    try:
        from interface.config import DB_USUARIOS_PATH
    except ImportError:
        from config import DB_USUARIOS_PATH
    ruta = os.environ.get("VMPOS_DB_USUARIOS") or DB_USUARIOS_PATH
    return sqlite3.connect(ruta)

