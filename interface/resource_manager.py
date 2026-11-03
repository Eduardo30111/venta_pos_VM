#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gestor de recursos para PyInstaller
Maneja las rutas de archivos y recursos cuando la aplicación está compilada
"""

import sys
import os

def get_resource_path(relative_path):
    """
    Obtiene la ruta absoluta de un recurso, funciona tanto en desarrollo como compilado.
    
    Args:
        relative_path (str): Ruta relativa del recurso
    
    Returns:
        str: Ruta absoluta del recurso
    """
    try:
        # PyInstaller crea una carpeta temporal y almacena la ruta en _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        # Si no está compilado, usar la ruta del script actual
        base_path = os.path.abspath(os.path.dirname(__file__))
        # Subir un nivel para llegar a la raíz del proyecto
        base_path = os.path.dirname(base_path)
    
    return os.path.join(base_path, relative_path)

def get_database_path():
    """Obtiene la ruta de la base de datos principal."""
    return get_resource_path(os.path.join("database", "ventas.db"))

def get_users_database_path():
    """Obtiene la ruta de la base de datos de usuarios."""
    return get_resource_path(os.path.join("database", "usuarios.db"))

def get_assets_path():
    """Obtiene la ruta de la carpeta de assets."""
    return get_resource_path("assets")

def get_reports_path():
    """Obtiene la ruta de la carpeta de reportes."""
    return get_resource_path("reports_pdf")

def get_excel_reports_path():
    """Obtiene la ruta de la carpeta de reportes Excel."""
    return get_resource_path("reports_excel")

def get_backups_path():
    """Obtiene la ruta de la carpeta de backups."""
    return get_resource_path("backups")

def ensure_directories_exist():
    """
    Crea los directorios necesarios si no existen.
    Útil cuando la aplicación se ejecuta por primera vez.
    """
    directories = [
        get_resource_path("database"),
        get_resource_path("reports_pdf"),
        get_resource_path("reports_excel"),
        get_resource_path("backups"),
        get_resource_path("config")
    ]
    
    for directory in directories:
        try:
            os.makedirs(directory, exist_ok=True)
            print(f"✅ Directorio verificado: {directory}")
        except Exception as e:
            print(f"❌ Error creando directorio {directory}: {e}")

def is_compiled():
    """
    Verifica si la aplicación está ejecutándose como ejecutable compilado.
    
    Returns:
        bool: True si está compilado, False si está en desarrollo
    """
    return getattr(sys, 'frozen', False)

def get_app_directory():
    """
    Obtiene el directorio donde se encuentra la aplicación.
    
    Returns:
        str: Ruta del directorio de la aplicación
    """
    if is_compiled():
        # Si está compilado, usar el directorio del ejecutable
        return os.path.dirname(sys.executable)
    else:
        # Si está en desarrollo, usar el directorio del proyecto
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def copy_database_to_app_dir():
    """
    Copia las bases de datos al directorio de la aplicación si no existen.
    Útil para la primera ejecución del ejecutable.
    """
    if not is_compiled():
        return  # Solo necesario para ejecutables
    
    app_dir = get_app_directory()
    database_dir = os.path.join(app_dir, "database")
    
    # Crear directorio database si no existe
    try:
        os.makedirs(database_dir, exist_ok=True)
    except OSError:
        return
    
    # Rutas de las bases de datos
    databases = [
        ("ventas.db", get_database_path()),
        ("usuarios.db", get_users_database_path())
    ]
    
    for db_name, source_path in databases:
        dest_path = os.path.join(database_dir, db_name)
        
        # Si la base de datos no existe en el directorio de la app, copiarla
        if not os.path.exists(dest_path) and os.path.exists(source_path):
            try:
                import shutil
                shutil.copy2(source_path, dest_path)
                print(f"✅ Base de datos copiada: {db_name}")
            except Exception as e:
                print(f"❌ Error copiando {db_name}: {e}")

# Inicializar directorios al importar el módulo
if __name__ == "__main__":
    print("🔧 Inicializando gestor de recursos...")
    ensure_directories_exist()
    if is_compiled():
        copy_database_to_app_dir()
    print("✅ Gestor de recursos listo")