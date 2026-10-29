import re

# Parchear ventas_menu.py
with open("interface/ventas_menu.py", "r") as f:
    vcode = f.read()

v_old = """todos_los_productos.append((p.get("codigo", ""), p.get("nombre", ""), p.get("stock", 0), p.get("precio_venta", p.get("precio", 0.0)), p.get("tipo_producto", "Fisico"), p.get("proveedor_id"), p.get("id"), p.get("precio_costo", p.get("costo", 0.0))))"""

# El código actual de ventas_menu usa:
# todos_los_productos.append((p.get("codigo", ""), p.get("nombre", ""), p.get("stock", 0), p.get("precio", 0.0), p.get("tipo_producto", "Fisico"), p.get("proveedor_id"), p.get("id"), p.get("costo", 0.0)))
vcode = re.sub(r'todos_los_productos\.append\(\(p\.get\("codigo".*?p\.get\("stock", 0\).*?\)\)', 
               r'stock_val = p.get("stock", 0)\n                stock_fmt = int(stock_val) if float(stock_val).is_integer() else stock_val\n                todos_los_productos.append((p.get("codigo", ""), p.get("nombre", ""), stock_fmt, p.get("precio", 0.0), p.get("tipo_producto", "Fisico"), p.get("proveedor_id"), p.get("id"), p.get("costo", 0.0)))', 
               vcode)

with open("interface/ventas_menu.py", "w") as f:
    f.write(vcode)

# Parchear inventario_menu.py
with open("interface/inventario_menu.py", "r") as f:
    icode = f.read()

icode = re.sub(r'prov_nombre = p\.get\("proveedor", \{\}\)\.get\("nombre"\) if p\.get\("proveedor"\) else "Ninguno"\n\s+resultados\.append\(\(p\.get\("id"\).*?p\.get\("stock"\).*?\)\)',
               r'prov_nombre = p.get("proveedor", {}).get("nombre") if p.get("proveedor") else "Ninguno"\n            stock_val = p.get("stock", 0)\n            stock_fmt = int(stock_val) if float(stock_val).is_integer() else stock_val\n            resultados.append((p.get("id"), p.get("codigo"), p.get("nombre"), p.get("precio_venta"), p.get("precio_costo"), stock_fmt, "Fisico", prov_nombre))',
               icode)

with open("interface/inventario_menu.py", "w") as f:
    f.write(icode)

print("STOCK ESTETICO PARCHEADO")
