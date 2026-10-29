import re
import glob

for filepath in glob.glob("interface/*_menu.py"):
    with open(filepath, "r") as f:
        code = f.read()

    # Patrón común donde hacen = resp.json()
    # Queremos reemplazarlo o asegurarnos de extraer "items" si es un diccionario.
    # Pero cada módulo puede llamarlo diferente. Lo más seguro es inyectar una función de ayuda en api_client.py
    pass

# Mejor parcheamos las líneas específicas de ventas_menu.py
with open("interface/ventas_menu.py", "r") as f:
    vcode = f.read()

v_old = """productos = resp_prod.json()
            servicios = resp_serv.json()"""
v_new = """prod_data = resp_prod.json()
            serv_data = resp_serv.json()
            productos = prod_data.get("items", []) if isinstance(prod_data, dict) else (prod_data if isinstance(prod_data, list) else [])
            servicios = serv_data.get("items", []) if isinstance(serv_data, dict) else (serv_data if isinstance(serv_data, list) else [])"""
vcode = vcode.replace(v_old, v_new)

v_old2 = """clientes = resp.json()"""
v_new2 = """c_data = resp.json()
                    clientes = c_data.get("items", []) if isinstance(c_data, dict) else (c_data if isinstance(c_data, list) else [])"""
vcode = vcode.replace(v_old2, v_new2)

with open("interface/ventas_menu.py", "w") as f:
    f.write(vcode)

# Parche clientes_menu.py
with open("interface/clientes_menu.py", "r") as f:
    ccode = f.read()
c_old = """clientes = response.json()"""
c_new = """c_data = response.json()
            clientes = c_data.get("items", []) if isinstance(c_data, dict) else (c_data if isinstance(c_data, list) else [])"""
ccode = ccode.replace(c_old, c_new)
with open("interface/clientes_menu.py", "w") as f:
    f.write(ccode)

print("MÓDULOS DE VENTAS Y CLIENTES PARCHEADOS")
