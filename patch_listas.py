import re

with open("interface/inventario_menu.py", "r") as f:
    code = f.read()

new_obtener_productos = """def obtener_productos():
    try:
        productos_data = api.get("/productos?size=1000")
        servicios_data = api.get("/servicios?size=1000")
        
        productos = productos_data.get("items", []) if isinstance(productos_data, dict) else (productos_data if isinstance(productos_data, list) else [])
        servicios = servicios_data.get("items", []) if isinstance(servicios_data, dict) else (servicios_data if isinstance(servicios_data, list) else [])
        
        resultados = []
        for p in productos:
            prov_nombre = p.get("proveedor", {}).get("nombre") if p.get("proveedor") else "Ninguno"
            resultados.append((p.get("id"), p.get("codigo"), p.get("nombre"), p.get("precio_venta"), p.get("precio_costo"), p.get("stock"), "Fisico", prov_nombre))
        for s in servicios:
            resultados.append((s.get("id"), s.get("codigo"), s.get("nombre"), s.get("precio_venta"), s.get("costo_proveedor"), 0, "Servicio", "Ninguno"))
        return resultados
    except Exception as e:"""
code = re.sub(r'def obtener_productos\(\):.*?except Exception as e:', new_obtener_productos, code, flags=re.DOTALL)

new_obtener_proveedores = """def obtener_proveedores():
    try:
        proveedores_data = api.get("/proveedores?size=1000")
        proveedores = proveedores_data.get("items", []) if isinstance(proveedores_data, dict) else (proveedores_data if isinstance(proveedores_data, list) else [])
        return [(p.get("id"), p.get("nombre")) for p in proveedores]
    except:"""
code = re.sub(r'def obtener_proveedores\(\):.*?except:', new_obtener_proveedores, code, flags=re.DOTALL)

with open("interface/inventario_menu.py", "w") as f:
    f.write(code)
print("LISTAS PARCHEADAS")
