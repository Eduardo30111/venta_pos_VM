with open("interface/menu_inicio.py", "r") as f:
    content = f.read()

import re

old_permisos = '''PERMISOS = {
    "administrador": {
        "Ventas": 1,
        "Inventario": 1,
        "Clientes": 1,
        "Reportes": 1,
        "Gastos": 1,
        "Usuarios": 1,
        "Configuración": 1,
        "Códigos de Barras": 1, "Nómina": 1
    },
    "admin": {  # Agregar alias para administrador
        "Ventas": 1,
        "Inventario": 1,
        "Clientes": 1,
        "Reportes": 1,
        "Gastos": 1,
        "Usuarios": 1,
        "Configuración": 1,
        "Códigos de Barras": 1, "Nómina": 1
    },
    "vendedor": {
        "Ventas": 1,
        "Inventario": 1,
        "Clientes": 1,
        "Reportes": 1,
        "Gastos": 0,
        "Usuarios": 0,
        "Configuración": 0,
        "Códigos de Barras": 1, "Nómina": 1
    },
    "gerente": {
        "Ventas": 1,
        "Inventario": 1,
        "Clientes": 1,
        "Reportes": 1,
        "Gastos": 0,
        "Usuarios": 1,
        "Configuración": 1,
        "Códigos de Barras": 1, "Nómina": 1
    },
    "empleado": {
        "Ventas": 1,
        "Inventario": 0,
        "Clientes": 0,
        "Reportes": 0,
        "Gastos": 0,
        "Usuarios": 0,
        "Configuración": 0,
        "Códigos de Barras": 0
    }
}'''

new_permisos = '''PERMISOS = {
    "administrador": {
        "Ventas": 1, "Inventario": 1, "Clientes": 1, "Reportes": 1, "Gastos": 1,
        "Usuarios": 1, "Configuración": 1, "Códigos de Barras": 1, "Nómina": 1
    },
    "admin": {
        "Ventas": 1, "Inventario": 1, "Clientes": 1, "Reportes": 1, "Gastos": 1,
        "Usuarios": 1, "Configuración": 1, "Códigos de Barras": 1, "Nómina": 1
    },
    "gerente": {
        "Ventas": 1, "Inventario": 1, "Clientes": 1, "Reportes": 1, "Gastos": 1,
        "Usuarios": 1, "Configuración": 0, "Códigos de Barras": 1, "Nómina": 1
    },
    "vendedor": {
        "Ventas": 1, "Inventario": 0, "Clientes": 0, "Reportes": 0, "Gastos": 0,
        "Usuarios": 0, "Configuración": 0, "Códigos de Barras": 0, "Nómina": 0
    },
    "operario": {
        "Ventas": 1, "Inventario": 0, "Clientes": 0, "Reportes": 0, "Gastos": 0,
        "Usuarios": 0, "Configuración": 0, "Códigos de Barras": 0, "Nómina": 0
    },
    "empleado": {
        "Ventas": 1, "Inventario": 0, "Clientes": 0, "Reportes": 0, "Gastos": 0,
        "Usuarios": 0, "Configuración": 0, "Códigos de Barras": 0, "Nómina": 0
    }
}'''

content = content.replace(old_permisos, new_permisos)

# Also update logic in menu_inicio.py to support operario
content = content.replace('["empleado", "vendedor"]', '["empleado", "vendedor", "operario"]')

with open("interface/menu_inicio.py", "w") as f:
    f.write(content)
