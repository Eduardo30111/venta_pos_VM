import re

with open("interface/inventario_menu.py", "r") as f:
    content = f.read()

old_def = '''def actualizar_producto(id_producto, nombre, precio, costo, stock, tipo_producto="Fisico", proveedor_id=None):
    """Actualiza los datos de un producto existente"""
    try:
        conn = conectar_db()
        if not conn:
            return False
        
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE productos
            SET nombre = ?, precio = ?, costo = ?, stock = ?, tipo_producto = ?, proveedor_id = ?
            WHERE id = ?
        """, (nombre, precio, costo, stock, tipo_producto, proveedor_id, id_producto))'''

new_def = '''def actualizar_producto(id_producto, nombre, precio, costo, stock, tipo_producto="Fisico", proveedor_id=None, descripcion=""):
    """Actualiza los datos de un producto existente"""
    try:
        conn = conectar_db()
        if not conn:
            return False
        
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE productos
            SET nombre = ?, precio = ?, costo = ?, stock = ?, tipo_producto = ?, proveedor_id = ?, descripcion = ?
            WHERE id = ?
        """, (nombre, precio, costo, stock, tipo_producto, proveedor_id, descripcion, id_producto))'''

content = content.replace(old_def, new_def)

with open("interface/inventario_menu.py", "w") as f:
    f.write(content)
