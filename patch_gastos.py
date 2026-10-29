import re

with open("interface/gastos_menu.py", "r") as f:
    gcode = f.read()

g_old = """gastos = response.json()"""
g_new = """g_data = response.json()
            gastos = g_data.get("items", []) if isinstance(g_data, dict) else (g_data if isinstance(g_data, list) else [])"""

gcode = gcode.replace(g_old, g_new)

with open("interface/gastos_menu.py", "w") as f:
    f.write(gcode)

# Revisamos la nómina
with open("interface/nomina_menu.py", "r") as f:
    ncode = f.read()

n_old = """empleados = api.get("/nomina/empleados")"""
n_new = """emp_data = api.get("/nomina/empleados")
            empleados = emp_data.json().get("items", []) if hasattr(emp_data, "json") and isinstance(emp_data.json(), dict) else (emp_data.json() if hasattr(emp_data, "json") else emp_data)"""
ncode = ncode.replace(n_old, n_new)

n_old2 = """liq = api.get("/nomina/liquidaciones")"""
n_new2 = """liq_data = api.get("/nomina/liquidaciones")
            liq = liq_data.json().get("items", []) if hasattr(liq_data, "json") and isinstance(liq_data.json(), dict) else (liq_data.json() if hasattr(liq_data, "json") else liq_data)"""
ncode = ncode.replace(n_old2, n_new2)

with open("interface/nomina_menu.py", "w") as f:
    f.write(ncode)

print("TODO PARCHEADO")
