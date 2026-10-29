import sys, os
sys.path.append(os.getcwd())
from client.api_client import api

success, msg = api.login("admin", "admin123")
try:
    r = api.get("/productos?size=1000")
    productos_data = r.json()
    productos = productos_data.get("items", [])
    print(f"Total extraídos reales: {len(productos)}")
    for p in productos:
        print(f"Producto extraído: {p.get('nombre')}")
except Exception as e:
    import traceback
    traceback.print_exc()
